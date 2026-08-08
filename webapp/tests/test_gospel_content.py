#!/usr/bin/env python3
"""Tests for the shared content helpers: normalisation, extraction,
classification, and the on-disk cache."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gospel_content import (  # noqa: E402
    BUCKETS,
    HIGHLIGHT_URI,
    VERSE_ANCHOR,
    CacheError,
    cache_key,
    classify,
    extract_paragraphs,
    norm_text,
    read_cache,
    safe_url,
    validate_cache_doc,
    write_cache,
)


class NormaliseText(unittest.TestCase):
    def test_decodes_html_entities(self):
        # The live site serves 'D&amp;C' where other exports hold 'D&C'.
        # Missing this cost 12 of 119 anchors during investigation.
        self.assertEqual(norm_text("See D&amp;C 115:4"), "See D&C 115:4")

    def test_composes_unicode_to_nfc(self):
        decomposed = "Ravensbrück"      # u + combining diaeresis
        self.assertEqual(norm_text(decomposed), "Ravensbrück")

    def test_strips_tags_and_collapses_whitespace(self):
        self.assertEqual(norm_text("<p>a  \n b</p>"), "a b")

    def test_empty_and_none(self):
        self.assertEqual(norm_text(""), "")
        self.assertEqual(norm_text(None), "")


class ExtractParagraphs(unittest.TestCase):
    def test_extracts_paragraphs_with_pid(self):
        body = '<p data-aid="152799681" id="p25">Hello there.</p>'
        got = extract_paragraphs(body)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["para_id"], "p25")
        self.assertEqual(got[0]["pid"], "152799681")
        self.assertEqual(got[0]["text"], "Hello there.")

    def test_includes_headings(self):
        # A real annotation targets an <h2 id="p36">; matching only <p> drops it.
        body = ('<h2 data-aid="146039650" id="p36">Safeguarding Life</h2>'
                '<p id="p12">Body text.</p>')
        ids = [p["para_id"] for p in extract_paragraphs(body)]
        self.assertEqual(ids, ["p36", "p12"])

    def test_sort_follows_dom_order_not_id_number(self):
        # Live ids are non-contiguous and non-monotonic (…18, 59, 19…).
        body = '<p id="p18">a</p><p id="p59">b</p><p id="p19">c</p>'
        got = extract_paragraphs(body)
        self.assertEqual([p["para_id"] for p in got], ["p18", "p59", "p19"])
        self.assertEqual([p["sort"] for p in got], [0, 1, 2])

    def test_ignores_malformed_ids_and_empty_text(self):
        # Ids are accepted broadly because annotation anchors take many shapes;
        # only ids that cannot be anchors, and empty elements, are skipped.
        # Over-extraction is harmless: only referenced paragraphs are stored.
        body = ('<p id="3bad">x</p><p id="">y</p><p id="p3">   </p>'
                '<p id="p4">ok</p><p id="note1">a footnote</p>')
        self.assertEqual([p["para_id"] for p in extract_paragraphs(body)], ["p4", "note1"])

    def test_empty_body(self):
        self.assertEqual(extract_paragraphs(""), [])
        self.assertEqual(extract_paragraphs(None), [])

    def test_extracts_non_pn_anchor_shapes(self):
        # 574 real highlight entries target ids that are not pN: headings,
        # pull quotes, hymn lines, study summaries, and the opaque ids used in
        # talks from 2025 on. Requiring pN drops all of them.
        body = ('<h3 data-aid="142347917" id="title29">When a Council May Be Necessary</h3>'
                '<p data-aid="128078917" id="figure1_p29">Sacrifice brings forth blessings;</p>'
                '<p data-aid="128200172" id="aside2_p1">Life is full of difficulties.</p>'
                '<p data-aid="128432703" id="study_summary1">Murderers and adulterers.</p>'
                '<p data-aid="168179574" id="p_iilzI">For those with concerns.</p>')
        got = extract_paragraphs(body)
        self.assertEqual([p["para_id"] for p in got],
                         ["title29", "figure1_p29", "aside2_p1", "study_summary1", "p_iilzI"])
        self.assertEqual(got[0]["pid"], "142347917")


class AnchorParsing(unittest.TestCase):
    def test_matches_every_observed_anchor_shape(self):
        cases = {
            "/general-conference/2022/10/43gong.p25": ("p25", True),
            "/manual/general-handbook/32.title29": ("title29", False),
            "/liahona/2010/06/x.figure1_p29": ("figure1_p29", False),
            "/ensign/1996/06/x.aside2_p1": ("aside2_p1", False),
            "/general-conference/2025/10/51bednar.p_iilzI": ("p_iilzI", False),
            "/scriptures/ot/gen/6.study_summary1": ("study_summary1", False),
        }
        for uri, (anchor, is_verse) in cases.items():
            match = HIGHLIGHT_URI.match(uri)
            self.assertIsNotNone(match, uri)
            self.assertEqual(match.group(2), anchor)
            self.assertEqual(bool(VERSE_ANCHOR.match(anchor)), is_verse, uri)

    def test_handbook_section_number_is_not_an_anchor(self):
        # '/handbook/handbook-2-administering-the-church/8.1' -- the '.1' is
        # part of the section address, not a paragraph anchor.
        self.assertIsNone(HIGHLIGHT_URI.match("/handbook/handbook-2/8.1"))
        self.assertIsNone(HIGHLIGHT_URI.match("/manual/general-handbook/32.2"))

    def test_uri_with_no_anchor_does_not_match(self):
        self.assertIsNone(HIGHLIGHT_URI.match("/general-conference/2022/10/43gong"))


class SafeUrl(unittest.TestCase):
    def test_allows_http_and_https(self):
        self.assertEqual(safe_url("https://www.churchofjesuschrist.org/study/x"),
                         "https://www.churchofjesuschrist.org/study/x")
        self.assertEqual(safe_url("http://localhost/x"), "http://localhost/x")

    def test_rejects_script_and_other_schemes(self):
        # Cache documents are untrusted input and canonical_url is rendered as
        # an href, so a javascript: URL would run in the app's origin.
        for bad in ["javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,x",
                    "vbscript:x", "//evil.example/x", "/relative", "", None, 5]:
            self.assertIsNone(safe_url(bad), repr(bad))

    def test_stripped_from_a_cache_document(self):
        doc = validate_cache_doc({"uri": "/a", "canonical_url": "javascript:alert(1)",
                                  "paragraphs": []})
        self.assertIsNone(doc["canonical_url"])


class Classify(unittest.TestCase):
    def test_roots(self):
        cases = {
            "/scriptures/bofm/alma/27": "Scriptures",
            "/general-conference/2022/10/43gong": "General Conference",
            "/ensign/1987/09/a-talk": "Magazines",
            "/liahona/2010/06/x": "Magazines",
            "/history/saints-v1/21": "Church History",
            "/church-historians-press/x": "Church History",
            "/broadcasts/article/x": "Videos & Images",
            "/handbook/handbook-2-administering-the-church/8.1": "Handbooks & Callings",
            "/journal": "My Notes",
        }
        for uri, bucket in cases.items():
            self.assertEqual(classify(uri), bucket, uri)

    def test_manual_slug_rules(self):
        cases = {
            "/manual/come-follow-me-for-individuals-and-families-book-of-mormon-2020": "Come, Follow Me",
            "/manual/gospel-topics": "Topics",
            "/manual/gospel-topics-essays/x": "Church History",
            "/manual/revelations-in-context/x": "Church History",
            "/manual/hymns/praise-to-the-man": "Music",
            "/manual/childrens-songbook/x": "Music",
            "/manual/general-handbook/32": "Handbooks & Callings",
            "/manual/my-calling-as-a-counselor": "Handbooks & Callings",
            "/manual/jesus-the-christ/chapter-26": "Books & Lessons",
            "/manual/true-to-the-faith/x": "Books & Lessons",
        }
        for uri, bucket in cases.items():
            self.assertEqual(classify(uri), bucket, uri)

    def test_preach_my_gospel_overrides_category_name(self):
        # Owner's decision: both editions go to Books & Lessons, even though the
        # 2023 edition carries CategoryName 'Handbooks and Callings'.
        self.assertEqual(
            classify("/manual/preach-my-gospel-a-guide-to-missionary-service/x"),
            "Books & Lessons")
        self.assertEqual(
            classify("/manual/preach-my-gospel-2023/x", "Handbooks and Callings"),
            "Books & Lessons")

    def test_category_name_is_only_a_tiebreaker(self):
        # URI root wins even when CategoryName disagrees...
        self.assertEqual(classify("/ensign/1987/09/x", "Church History"), "Magazines")
        # ...but breaks ties /manual alone cannot.
        self.assertEqual(classify("/manual/mental-health-help-for-me", "Life Help"), "Other")
        self.assertEqual(classify("/manual/unknown-thing", "Come, Follow Me"), "Come, Follow Me")

    def test_unknown_root_falls_to_other_never_dropped(self):
        self.assertEqual(classify("/some-future-namespace/x"), "Other")

    def test_no_uri_is_my_notes(self):
        self.assertEqual(classify(None), "My Notes")
        self.assertEqual(classify(""), "My Notes")

    def test_every_bucket_is_declared(self):
        for uri in ["/scriptures/x/y/1", "/general-conference/a/b/c", "/manual/hymns/x",
                    "/some-future-namespace/x", None]:
            self.assertIn(classify(uri), BUCKETS)


class ValidateCacheDoc(unittest.TestCase):
    def good(self):
        return {"uri": "/general-conference/2022/10/43gong",
                "paragraphs": [{"para_id": "p25", "pid": "1", "sort": 0, "text": "Hi"}]}

    def test_accepts_and_normalises(self):
        doc = validate_cache_doc(self.good())
        self.assertEqual(doc["paragraphs"][0]["para_id"], "p25")
        self.assertFalse(doc["restricted"])

    def test_rejects_uri_not_matching_filename_hash(self):
        with self.assertRaises(CacheError):
            validate_cache_doc(self.good(), expected_key="0" * 64)

    def test_accepts_matching_hash(self):
        doc = self.good()
        validate_cache_doc(doc, expected_key=cache_key(doc["uri"]))

    def test_rejects_bad_shapes(self):
        for bad in [
            [],                                                     # not an object
            {"paragraphs": []},                                     # no uri
            {"uri": "no-leading-slash", "paragraphs": []},
            {"uri": "/a", "paragraphs": "nope"},
            {"uri": "/a", "paragraphs": [{"para_id": "1bad", "text": "t"}]},  # id must start alpha
            {"uri": "/a", "paragraphs": [{"para_id": "has space", "text": "t"}]},
            {"uri": "/a", "paragraphs": [{"para_id": "p1", "text": 5}]},     # bad text
            {"uri": "/a", "paragraphs": [{"para_id": "p1", "text": "a"},
                                         {"para_id": "p1", "text": "b"}]},   # duplicate
        ]:
            with self.assertRaises(CacheError, msg=repr(bad)):
                validate_cache_doc(bad)

    def test_accepts_non_pn_para_ids(self):
        doc = validate_cache_doc({"uri": "/a", "paragraphs": [
            {"para_id": "title29", "text": "A heading"},
            {"para_id": "p_iilzI", "text": "Opaque id"}]})
        self.assertEqual([p["para_id"] for p in doc["paragraphs"]], ["title29", "p_iilzI"])

    def test_text_is_always_normalised_even_without_markup(self):
        # Skipping normalisation for text with no '<' made the same paragraph
        # compare unequal depending on which source it came from, and changed
        # the word count that highlight spans are clamped against.
        doc = validate_cache_doc({"uri": "/a", "paragraphs": [
            {"para_id": "p1", "text": "D&amp;C 121  and  more"}]})
        self.assertEqual(doc["paragraphs"][0]["text"], "D&C 121 and more")

    def test_error_is_carried_and_truncated(self):
        doc = validate_cache_doc({"uri": "/a", "paragraphs": [], "error": "HTTP 404"})
        self.assertEqual(doc["error"], "HTTP 404")
        long = validate_cache_doc({"uri": "/a", "paragraphs": [], "error": "x" * 500})
        self.assertEqual(len(long["error"]), 200)

    def test_empty_paragraph_list_is_valid(self):
        doc = validate_cache_doc({"uri": "/a", "paragraphs": []})
        self.assertEqual(doc["paragraphs"], [])


class CacheRoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_write_then_read(self):
        write_cache(self.dir, {"uri": "/a/b", "paragraphs":
                               [{"para_id": "p1", "text": "hello", "sort": 0}]})
        docs = read_cache(self.dir)
        self.assertIn("/a/b", docs)
        self.assertEqual(docs["/a/b"]["paragraphs"][0]["text"], "hello")

    def test_write_is_idempotent(self):
        doc = {"uri": "/a/b", "paragraphs": [{"para_id": "p1", "text": "hello", "sort": 0}]}
        write_cache(self.dir, doc)
        write_cache(self.dir, doc)
        self.assertEqual(len(os.listdir(self.dir)), 1)
        self.assertEqual(len(read_cache(self.dir)["/a/b"]["paragraphs"]), 1)

    def test_corrupt_file_is_skipped_not_fatal(self):
        write_cache(self.dir, {"uri": "/good", "paragraphs":
                               [{"para_id": "p1", "text": "x", "sort": 0}]})
        with open(os.path.join(self.dir, "a" * 64 + ".json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        warnings = []
        docs = read_cache(self.dir, warn=warnings.append)
        self.assertEqual(list(docs), ["/good"])
        self.assertEqual(len(warnings), 1)

    def test_hash_mismatch_is_skipped(self):
        path = os.path.join(self.dir, "b" * 64 + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"uri": "/mismatched", "paragraphs": []}, f)
        warnings = []
        self.assertEqual(read_cache(self.dir, warn=warnings.append), {})
        self.assertEqual(len(warnings), 1)

    def test_missing_directory_is_empty_not_an_error(self):
        self.assertEqual(read_cache(os.path.join(self.dir, "nope")), {})
        self.assertEqual(read_cache(None), {})


if __name__ == "__main__":
    unittest.main()
