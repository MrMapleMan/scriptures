#!/usr/bin/env python3
"""Tests for the dataset build: retention, classification, offset mapping,
paragraph anchoring, and the guarantee that the build never uses the network."""

import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_data  # noqa: E402
from gospel_content import write_cache  # noqa: E402

VERSE_DDL = """
CREATE TABLE verses (
    volume_lds_url TEXT, volume_title TEXT, book_lds_url TEXT, book_title TEXT,
    book_long_title TEXT, chapter_number INTEGER, verse_number INTEGER, scripture_text TEXT
);
"""

ANN_DDL = """
CREATE TABLE AnnotationStorage (
    AnnotationId TEXT, Type TEXT, Uri TEXT, ItemTitle TEXT, Location TEXT, SubLocation TEXT,
    CategoryName TEXT, NoteTitle TEXT, NoteContent TEXT, Highlights TEXT, Refs TEXT,
    Content TEXT, Created TEXT, Timestamp TEXT
);
"""

ANN_COLS = ("AnnotationId, Type, Uri, ItemTitle, Location, SubLocation, CategoryName, "
            "NoteTitle, NoteContent, Highlights, Refs, Content, Created, Timestamp")


def highlight(uri, pid=None, start=-1, end=-1, color="yellow"):
    return {"Uri": uri, "Pid": pid, "OffsetStart": start, "OffsetEnd": end,
            "Color": color, "Style": None}


class BuildFixture(unittest.TestCase):
    """A tiny but complete pair of source databases, built per test."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = os.path.join(self.dir, "cache")
        self.verses_path = os.path.join(self.dir, "verses.db")
        self.ann_path = os.path.join(self.dir, "ann.db")

        v = sqlite3.connect(self.verses_path)
        v.executescript(VERSE_DDL)
        v.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?,?)", [
            ("bofm", "Book of Mormon", "alma", "Alma", "The Book of Alma", 27, 4,
             "And it came to pass that they did go forth quickly."),
            ("bofm", "Book of Mormon", "alma", "Alma", "The Book of Alma", 27, 5,
             "Second verse of the chapter here."),
        ])
        v.commit()
        v.close()

        self.ann = sqlite3.connect(self.ann_path)
        self.ann.executescript(ANN_DDL)

    def tearDown(self):
        self.ann.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def add(self, aid, uri="", highlights=None, note_title="", note_content="",
            atype="highlight", category=None, location="", sub_location="", item_title="",
            tags=None):
        content = json.dumps({"Tags": tags or []})
        self.ann.execute(
            "INSERT INTO AnnotationStorage (%s) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)" % ANN_COLS,
            (aid, atype, uri, item_title, location, sub_location, category, note_title,
             note_content, json.dumps(highlights) if highlights is not None else None,
             None, content, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
        self.ann.commit()

    def build(self):
        out_path = os.path.join(self.dir, "out.sqlite")
        if os.path.exists(out_path):
            os.remove(out_path)
        src = sqlite3.connect("file:%s?mode=ro" % self.verses_path, uri=True)
        ann = sqlite3.connect("file:%s?mode=ro" % self.ann_path, uri=True)
        out = sqlite3.connect(out_path)
        out.executescript(build_data.SCHEMA)
        book_ids, verse_text = build_data.build_scriptures(src, out)
        from gospel_content import read_cache
        counts, categories = build_data.build_annotations(
            ann, out, book_ids, verse_text, read_cache(self.cache))
        out.commit()
        return out, counts, categories

    def kinds(self, out):
        return dict(out.execute("SELECT kind, COUNT(*) FROM annotations GROUP BY kind").fetchall())


class Retention(BuildFixture):
    def test_scripture_annotation_is_kept_as_scripture(self):
        self.add("a1", "/scriptures/bofm/alma/27",
                 [highlight("/scriptures/bofm/alma/27.p4")])
        out, counts, _ = self.build()
        self.assertEqual(self.kinds(out).get("scripture"), 1)
        self.assertEqual(counts["dropped"], 0)

    def test_conference_talk_is_kept_as_document(self):
        # The whole point: this used to be dropped outright.
        self.add("a2", "/general-conference/2022/10/43gong",
                 [highlight("/general-conference/2022/10/43gong.p25")])
        out, counts, _ = self.build()
        self.assertEqual(self.kinds(out).get("document"), 1)
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(out.execute("SELECT category FROM annotations WHERE id='a2'").fetchone()[0],
                         "General Conference")

    def test_note_without_uri_is_kept_as_note(self):
        self.add("a3", "", None, note_content="A journal entry.", atype="journal")
        out, counts, _ = self.build()
        self.assertEqual(self.kinds(out).get("note"), 1)
        self.assertEqual(counts["dropped"], 0)

    def test_row_with_no_uri_no_note_no_verse_is_dropped(self):
        self.add("a4", "", None)
        out, counts, _ = self.build()
        self.assertEqual(counts["dropped"], 1)
        self.assertEqual(self.kinds(out), {})

    def test_uri_without_note_is_retained_not_dropped(self):
        # A reference-type annotation with no highlights at all.
        self.add("a5", "/ensign/1987/09/a-talk", [], atype="reference")
        out, counts, _ = self.build()
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(self.kinds(out).get("document"), 1)

    def test_scripture_uri_with_unresolvable_verse_becomes_document(self):
        # Chapter heading / study summary case, and JST, BD, GS, OD.
        self.add("a6", "/scriptures/bofm/alma/27",
                 [highlight("/scriptures/bofm/alma/27.p999")])
        out, counts, _ = self.build()
        self.assertEqual(self.kinds(out).get("document"), 1)
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(out.execute("SELECT category FROM annotations WHERE id='a6'").fetchone()[0],
                         "Scriptures")

    def test_unknown_book_with_note_survives_as_document(self):
        self.add("a7", "/scriptures/jst/jst-matt/1",
                 [highlight("/scriptures/jst/jst-matt/1.p1")], note_content="note")
        out, counts, _ = self.build()
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(self.kinds(out).get("document"), 1)

    def test_journal_uri_is_a_note_not_a_document(self):
        # '/journal' names the notebook, not a page. Treating it as a document
        # gives it a reader that offers to download content that cannot exist.
        self.add("a8", "/journal", None, note_content="A journal entry.", atype="journal")
        out, counts, _ = self.build()
        self.assertEqual(self.kinds(out).get("note"), 1)
        self.assertEqual(out.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertEqual(out.execute(
            "SELECT category FROM annotations WHERE id='a8'").fetchone()[0], "My Notes")

    def test_non_pn_anchor_still_produces_a_highlight(self):
        # 574 real highlights target ids like title29 / p_iilzI, and 273
        # annotations have no pN anchor at all. Requiring pN left them with no
        # highlight rows, so the reader had nothing to show forever.
        uri = "/manual/general-handbook/32"
        self.add("d1", uri, [highlight(uri + ".title29", pid="142347917")])
        out, counts, _ = self.build()
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(out.execute(
            "SELECT para_id, pid FROM highlights").fetchone(), ("title29", "142347917"))

    def test_scripture_heading_anchor_does_not_become_a_verse(self):
        # '/scriptures/bofm/alma/27.study_summary1' is in the scripture
        # namespace but names no verse; int('tudy_summary1') would explode.
        self.add("a9", "/scriptures/bofm/alma/27",
                 [highlight("/scriptures/bofm/alma/27.study_summary1")])
        out, counts, _ = self.build()
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(self.kinds(out).get("document"), 1)

    def test_handbook_section_number_is_not_treated_as_an_anchor(self):
        uri = "/handbook/handbook-2-administering-the-church/8.1"
        self.add("d2", uri, [highlight(uri + ".p3")])
        out, _, _ = self.build()
        self.assertEqual(out.execute("SELECT uri FROM documents").fetchone()[0], uri)
        self.assertEqual(out.execute("SELECT para_id FROM highlights").fetchone()[0], "p3")


class Documents(BuildFixture):
    def test_document_row_created_once_per_uri(self):
        for i in range(3):
            self.add("d%d" % i, "/general-conference/2022/10/43gong",
                     [highlight("/general-conference/2022/10/43gong.p%d" % (i + 1))])
        out, _, _ = self.build()
        self.assertEqual(out.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)

    def test_uncached_document_is_unfetched_but_kept(self):
        self.add("d1", "/general-conference/2022/10/43gong",
                 [highlight("/general-conference/2022/10/43gong.p25")])
        out, _, _ = self.build()
        self.assertEqual(
            out.execute("SELECT fetch_state FROM documents").fetchone()[0], "unfetched")
        self.assertEqual(out.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0], 0)
        self.assertEqual(out.execute("SELECT COUNT(*) FROM highlights").fetchone()[0], 1)

    def test_cached_document_embeds_paragraphs(self):
        uri = "/general-conference/2022/10/43gong"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p25", "pid": "152799681", "sort": 0, "text": "one two three four"}]})
        self.add("d1", uri, [highlight(uri + ".p25")])
        out, _, _ = self.build()
        self.assertEqual(out.execute("SELECT fetch_state FROM documents").fetchone()[0], "cached")
        self.assertEqual(out.execute("SELECT text FROM paragraphs").fetchone()[0],
                         "one two three four")

    def test_cached_document_with_no_paragraphs_is_empty_not_failed(self):
        uri = "/broadcasts/article/video-only"
        write_cache(self.cache, {"uri": uri, "paragraphs": []})
        self.add("d1", uri, [highlight(uri + ".p1")])
        out, _, _ = self.build()
        self.assertEqual(out.execute("SELECT fetch_state FROM documents").fetchone()[0], "empty")

    def test_pid_wins_over_para_id(self):
        # Content was revised: the annotation's p9 now lives at p12, but the
        # data-aid is unchanged, so Pid-first anchoring still finds it.
        uri = "/general-conference/2022/10/43gong"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p9", "pid": "OTHER", "sort": 0, "text": "wrong paragraph"},
            {"para_id": "p12", "pid": "STABLE", "sort": 1, "text": "right paragraph"}]})
        self.add("d1", uri, [highlight(uri + ".p9", pid="STABLE")])
        out, _, _ = self.build()
        row = out.execute("SELECT para_id, pid FROM highlights").fetchone()
        self.assertEqual(row, ("p12", "STABLE"))

    def test_falls_back_to_para_id_when_pid_absent(self):
        uri = "/general-conference/2022/10/43gong"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p9", "pid": None, "sort": 0, "text": "the paragraph"}]})
        self.add("d1", uri, [highlight(uri + ".p9")])
        out, _, _ = self.build()
        self.assertEqual(out.execute("SELECT para_id FROM highlights").fetchone()[0], "p9")

    def test_anchor_missing_from_content_keeps_row_without_span(self):
        uri = "/general-conference/2021/04/26andersen"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p12", "pid": None, "sort": 0, "text": "present"}]})
        self.add("d1", uri, [highlight(uri + ".p36")])   # heading the scrape dropped
        out, _, _ = self.build()
        row = out.execute(
            "SELECT para_id, word_start, word_end FROM highlights").fetchone()
        self.assertEqual(row, ("p36", None, None))

    def test_only_referenced_paragraphs_are_embedded_outside_conference(self):
        # A cache document holds the whole page so the Pid fallback has
        # something to match against, but embedding all of it would multiply the
        # dataset by the length of every manual chapter. R15 exempts General
        # Conference only, so this uses a manual URI.
        uri = "/manual/jesus-the-christ/chapter-26"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p%d" % i, "pid": "aid%d" % i, "sort": i, "text": "para %d" % i}
            for i in range(1, 21)]})
        self.add("d1", uri, [highlight(uri + ".p3")])
        out, _, _ = self.build()
        rows = out.execute("SELECT para_id FROM paragraphs").fetchall()
        self.assertEqual(rows, [("p3",)])

    def test_general_conference_embeds_the_whole_talk(self):
        # R15: a talk is short and its full text is already held locally, so the
        # reader gets the paragraphs around the annotation as context.
        uri = "/general-conference/2022/10/43gong"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p%d" % i, "pid": "aid%d" % i, "sort": i, "text": "para %d" % i}
            for i in range(1, 21)]})
        self.add("d1", uri, [highlight(uri + ".p3")])
        out, _, _ = self.build()
        rows = [r[0] for r in out.execute(
            "SELECT para_id FROM paragraphs ORDER BY sort").fetchall()]
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[:3], ["p1", "p2", "p3"])

    def test_namespace_split_holds_within_one_build(self):
        """R15a: the risk is implementing this as a global change.

        Both documents are cached in the same build with one annotation each;
        only the conference talk may keep its unreferenced paragraphs.
        """
        talk = "/general-conference/2022/10/43gong"
        manual = "/manual/general-handbook/32-repentance-and-membership-councils"
        for uri in (talk, manual):
            write_cache(self.cache, {"uri": uri, "paragraphs": [
                {"para_id": "p%d" % i, "pid": "%s-aid%d" % (uri[-4:], i),
                 "sort": i, "text": "para %d" % i}
                for i in range(1, 11)]})
            self.add("a" + uri[-4:], uri, [highlight(uri + ".p2")])
        out, _, _ = self.build()
        counts = dict(out.execute(
            "SELECT doc_uri, COUNT(*) FROM paragraphs GROUP BY doc_uri").fetchall())
        self.assertEqual(counts[talk], 10)
        self.assertEqual(counts[manual], 1)

    def test_referenced_paragraph_is_kept_under_its_new_number(self):
        # Content revised: the anchor is now p12, matched via the stable Pid.
        # The paragraph must survive the referenced-only filter under either id.
        # Non-conference, so the filter is actually exercised.
        uri = "/manual/jesus-the-christ/chapter-26"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p1", "pid": "other", "sort": 0, "text": "unrelated"},
            {"para_id": "p12", "pid": "STABLE", "sort": 1, "text": "the annotated one"}]})
        self.add("d1", uri, [highlight(uri + ".p9", pid="STABLE")])
        out, _, _ = self.build()
        self.assertEqual(out.execute("SELECT para_id, text FROM paragraphs").fetchall(),
                         [("p12", "the annotated one")])

    def test_cached_document_with_an_error_is_failed(self):
        # A permanently gone page (the retired Handbook 2 returns 404) is
        # recorded rather than retried on every build.
        uri = "/handbook/handbook-2-administering-the-church/melchizedek-priesthood"
        write_cache(self.cache, {"uri": uri, "paragraphs": [], "error": "HTTP 404"})
        self.add("d1", uri, [highlight(uri + ".p1")])
        out, _, _ = self.build()
        self.assertEqual(out.execute(
            "SELECT fetch_state, fetch_error FROM documents").fetchone(), ("failed", "HTTP 404"))

    def test_document_metadata_is_carried_through(self):
        uri = "/general-conference/2022/10/43gong"
        self.add("d1", uri, [highlight(uri + ".p1")], location="Happy and Forever",
                 sub_location="Gerrit W. Gong", item_title="October 2022")
        out, _, _ = self.build()
        row = out.execute("SELECT title, subtitle, item_title FROM documents").fetchone()
        self.assertEqual(row, ("Happy and Forever", "Gerrit W. Gong", "October 2022"))


class ClampSpan(unittest.TestCase):
    def test_minus_one_runs_to_the_edges(self):
        self.assertEqual(build_data.clamp_span(-1, -1, 5, 1), (1, 5))
        self.assertEqual(build_data.clamp_span(None, None, 5, 1), (1, 5))

    def test_shift_is_applied(self):
        self.assertEqual(build_data.clamp_span(2, 4, 10, 1), (1, 3))
        self.assertEqual(build_data.clamp_span(2, 4, 10, 0), (2, 4))

    def test_out_of_range_is_clamped(self):
        self.assertEqual(build_data.clamp_span(1, 99, 5, 1), (1, 5))
        self.assertEqual(build_data.clamp_span(-5, 3, 5, 0), (1, 3))

    def test_reversed_pair_is_swapped(self):
        self.assertEqual(build_data.clamp_span(6, 3, 10, 1), (2, 5))

    def test_end_one_past_the_word_count_clamps_to_last_word(self):
        # 89 real highlights end at exactly word_count + 1.
        self.assertEqual(build_data.clamp_span(2, 6, 5, 1), (1, 5))

    def test_zero_length_text_yields_nothing(self):
        self.assertIsNone(build_data.clamp_span(1, 2, 0, 1))


class VerseHighlights(BuildFixture):
    def test_scripture_offsets_use_the_minus_one_shift(self):
        # "And it came to pass..." -- offset 2 means word 1 of the verse text.
        self.add("a1", "/scriptures/bofm/alma/27",
                 [highlight("/scriptures/bofm/alma/27.p4", start=2, end=4)])
        out, _, _ = self.build()
        self.assertEqual(
            out.execute("SELECT word_start, word_end FROM highlights").fetchone(), (1, 3))

    def test_document_highlights_are_whole_paragraph_until_shift_is_measured(self):
        # DOCUMENT_OFFSET_SHIFT is deliberately unset: a guessed shift silently
        # tints the wrong words, so a bounded highlight renders whole for now.
        self.assertIsNone(build_data.DOCUMENT_OFFSET_SHIFT)
        uri = "/general-conference/2022/10/43gong"
        write_cache(self.cache, {"uri": uri, "paragraphs": [
            {"para_id": "p25", "pid": None, "sort": 0, "text": "one two three four five"}]})
        self.add("d1", uri, [highlight(uri + ".p25", start=2, end=3)])
        out, _, _ = self.build()
        self.assertEqual(
            out.execute("SELECT word_start, word_end FROM highlights").fetchone(), (1, 5))


class NoNetwork(BuildFixture):
    def test_build_makes_no_network_connection(self):
        """R10: the build must be runnable with no connectivity at all."""
        uri = "/general-conference/2022/10/43gong"
        self.add("d1", uri, [highlight(uri + ".p25")])
        self.add("a1", "/scriptures/bofm/alma/27",
                 [highlight("/scriptures/bofm/alma/27.p4")])

        real_socket, real_create = socket.socket, socket.create_connection

        def forbidden(*args, **kwargs):
            raise AssertionError("build_data attempted a network connection")

        socket.socket, socket.create_connection = forbidden, forbidden
        try:
            out, counts, _ = self.build()
        finally:
            socket.socket, socket.create_connection = real_socket, real_create
        self.assertEqual(counts["dropped"], 0)
        self.assertEqual(self.kinds(out), {"document": 1, "scripture": 1})


class StripHtml(unittest.TestCase):
    def test_keeps_line_structure_and_bullets(self):
        got = build_data.strip_html("<div>one</div><ul><li>two</li></ul>")
        self.assertEqual(got, "one\n• two")

    def test_decodes_entities(self):
        self.assertEqual(build_data.strip_html("D&amp;C &quot;x&quot;"), 'D&C "x"')

    def test_empty(self):
        self.assertEqual(build_data.strip_html(None), "")
        self.assertEqual(build_data.strip_html(""), "")


if __name__ == "__main__":
    unittest.main()
