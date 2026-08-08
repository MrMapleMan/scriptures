#!/usr/bin/env python3
"""Tests for the conference-corpus alignment logic.

Pure functions only -- no network, and no dependency on the corpus database,
which lives outside the repo and is optional.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import build_alignment  # noqa: E402
from gospel_content import read_cache  # noqa: E402


def paras(pairs):
    return [{"para_id": pid, "pid": None, "sort": i, "text": text}
            for i, (pid, text) in enumerate(pairs)]


class Align(unittest.TestCase):
    def test_exact_sequence_maps_one_to_one(self):
        api = paras([("p1", "alpha"), ("p2", "beta"), ("p3", "gamma")])
        mapping, ratio = build_alignment.align(api, ["alpha", "beta", "gamma"], "", "")
        self.assertEqual(mapping, {"p1": 0, "p2": 1, "p3": 2})
        self.assertEqual(ratio, 1.0)

    def test_non_contiguous_ids_still_map_by_position(self):
        # Live ids run e.g. …18, 59, 19… because sidebars are interleaved.
        # Aligning on id number instead of sequence is what produced the
        # bogus 41% "mis-anchoring" result during investigation.
        api = paras([("p18", "one"), ("p59", "two"), ("p19", "three")])
        mapping, _ = build_alignment.align(api, ["one", "two", "three"], "", "")
        self.assertEqual(mapping, {"p18": 0, "p59": 1, "p19": 2})

    def test_leading_byline_is_synthesised_from_columns(self):
        # The scraper moved the byline/calling into their own columns, so p1/p2
        # are absent from the paragraph text entirely.
        api = paras([("p1", "By Elder David A. Bednar"),
                     ("p2", "Of the Quorum of the Twelve Apostles"),
                     ("p3", "body text")])
        mapping, _ = build_alignment.align(
            api, ["body text"], "By Elder David A. Bednar",
            "Of the Quorum of the Twelve Apostles")
        self.assertEqual(mapping["p1"], -1)
        self.assertEqual(mapping["p2"], -2)
        self.assertEqual(mapping["p3"], 0)

    def test_byline_not_synthesised_when_columns_disagree(self):
        api = paras([("p1", "Some body paragraph"), ("p2", "another")])
        mapping, _ = build_alignment.align(api, ["Some body paragraph", "another"],
                                           "By Elder Someone Else", "Of the Seventy")
        self.assertEqual(mapping, {"p1": 0, "p2": 1})

    def test_dropped_paragraph_is_simply_unmapped(self):
        # A heading the scrape omitted: it must not shift everything after it.
        api = paras([("p1", "one"), ("p36", "A Section Heading"), ("p2", "two")])
        mapping, _ = build_alignment.align(api, ["one", "two"], "", "")
        self.assertNotIn("p36", mapping)
        self.assertEqual(mapping["p1"], 0)
        self.assertEqual(mapping["p2"], 1)

    def test_empty_inputs(self):
        self.assertEqual(build_alignment.align([], [], "", "")[0], {})


class CorpusText(unittest.TestCase):
    def test_resolves_indexes_and_synthetic_slots(self):
        mapping = {"p1": -1, "p2": -2, "p3": 0}
        paragraphs = ["body"]
        self.assertEqual(
            build_alignment.corpus_text(mapping, "p1", paragraphs, "SPK", "CAL"), "SPK")
        self.assertEqual(
            build_alignment.corpus_text(mapping, "p2", paragraphs, "SPK", "CAL"), "CAL")
        self.assertEqual(
            build_alignment.corpus_text(mapping, "p3", paragraphs, "SPK", "CAL"), "body")

    def test_unmapped_or_out_of_range_returns_none(self):
        self.assertIsNone(build_alignment.corpus_text({}, "p9", ["a"], "", ""))
        self.assertIsNone(build_alignment.corpus_text({"p9": 7}, "p9", ["a"], "", ""))


class WriteFetched(unittest.TestCase):
    """R40a: the rejected-talk fallback is a GC writer, so R15 binds it too."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def read_one(self, uri):
        return read_cache(self.dir)[uri]

    def test_stores_the_whole_talk_not_only_the_anchors(self):
        uri = "/general-conference/2013/04/lord-i-believe"
        api = paras([("p%d" % i, "para %d" % i) for i in range(1, 13)])
        self.assertTrue(build_alignment.write_fetched(self.dir, uri, {}, api, {"p4"}))
        doc = self.read_one(uri)
        self.assertEqual(len(doc["paragraphs"]), 12)
        self.assertEqual(doc["source"], "fetched")

    def test_reports_but_keeps_a_talk_whose_anchor_is_gone(self):
        # The anchor the annotation wants was dropped by a later revision. The
        # talk is still worth caching -- the runtime can still resolve by Pid,
        # and the reader has a notice for the miss.
        uri = "/general-conference/2013/04/lord-i-believe"
        api = paras([("p1", "alpha"), ("p2", "beta")])
        self.assertTrue(build_alignment.write_fetched(self.dir, uri, {}, api, {"p99"}))
        self.assertEqual(len(self.read_one(uri)["paragraphs"]), 2)

    def test_empty_page_writes_nothing(self):
        self.assertFalse(
            build_alignment.write_fetched(self.dir, "/general-conference/x/y", {}, [], {"p1"}))
        self.assertEqual(read_cache(self.dir), {})


if __name__ == "__main__":
    unittest.main()
