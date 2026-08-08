#!/usr/bin/env python3
"""Acceptance checks against the real annotation export.

The synthetic fixtures in test_build_data.py exercise each rule in isolation,
which cannot catch a rule interaction that shifts the totals. These assert the
numeric criteria in the requirements (R3, R4, R7) against the actual export.

The export is personal data and is gitignored, so these skip when it is absent
rather than failing. No network is used.
"""

import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP = os.path.dirname(HERE)
REPO = os.path.dirname(WEBAPP)
sys.path.insert(0, WEBAPP)

import build_data  # noqa: E402
from gospel_content import read_cache  # noqa: E402

VERSES = os.path.join(REPO, "scripture_text.db")
EXPORT = os.path.join(REPO, "resources", "annotations",
                      "scripture_annotations_20260802.sqlite")

# R3 / R4, as amended in cycle 1.
EXPECTED_TOTAL = 9473
EXPECTED_DROPPED = 6
EXPECTED_KINDS = {"scripture": 5721, "document": 3132, "note": 614}
TOLERANCE = 0.01


@unittest.skipUnless(os.path.exists(VERSES) and os.path.exists(EXPORT),
                     "real export or scripture_text.db not present")
class RealExport(unittest.TestCase):
    """Built once for the whole class -- the real build takes a few seconds."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        out_path = os.path.join(cls.dir, "app.sqlite")
        src = sqlite3.connect("file:%s?mode=ro" % VERSES, uri=True)
        ann = sqlite3.connect("file:%s?mode=ro" % EXPORT, uri=True)
        cls.out = sqlite3.connect(out_path)
        cls.out.executescript(build_data.SCHEMA)
        book_ids, verse_text = build_data.build_scriptures(src, cls.out)
        # Deliberately an empty cache: this asserts the retention rules, which
        # must not depend on whether content has been downloaded.
        cls.counts, cls.categories = build_data.build_annotations(
            ann, cls.out, book_ids, verse_text, read_cache(None))
        cls.out.commit()

    @classmethod
    def tearDownClass(cls):
        cls.out.close()

    def test_r3_drops_exactly_six_rows(self):
        self.assertEqual(self.counts["dropped"], EXPECTED_DROPPED)

    def test_r4_kind_counts_within_one_percent(self):
        for kind, expected in EXPECTED_KINDS.items():
            got = self.counts[kind]
            self.assertLessEqual(
                abs(got - expected) / expected, TOLERANCE,
                "%s: got %d, expected %d (>1%% drift)" % (kind, got, expected))

    def test_every_row_is_accounted_for(self):
        total = sum(self.counts[k] for k in EXPECTED_KINDS) + self.counts["dropped"]
        self.assertEqual(total, EXPECTED_TOTAL)

    def test_no_annotation_is_uncategorised(self):
        rows = self.out.execute(
            "SELECT COUNT(*) FROM annotations WHERE category IS NULL OR category = ''").fetchone()
        self.assertEqual(rows[0], 0)

    def test_r7_journal_rows_are_notes_not_documents(self):
        self.assertEqual(
            self.out.execute("SELECT COUNT(*) FROM documents WHERE uri = '/journal'").fetchone()[0],
            0)
        self.assertGreater(self.categories["My Notes"], 600)

    def test_r7_null_category_rows_land_in_the_specified_buckets(self):
        """The 136 rows with a URI but no CategoryName, per R7's amended table."""
        from collections import Counter

        from gospel_content import classify
        con = sqlite3.connect("file:%s?mode=ro" % EXPORT, uri=True)
        buckets = Counter()
        for uri, cat in con.execute(
                "SELECT Uri, CategoryName FROM AnnotationStorage "
                "WHERE CategoryName IS NULL AND Uri IS NOT NULL AND Uri != ''"):
            buckets[classify(uri, cat)] += 1
        con.close()
        self.assertEqual(dict(buckets), {
            "Come, Follow Me": 54,
            "Books & Lessons": 53,
            "Handbooks & Callings": 24,
            "Other": 3,          # hear-him-launch, the parked open question
            "My Notes": 1,       # /journal
            "Scriptures": 1,
        })

    def test_non_pn_anchors_are_captured(self):
        # 574 real highlight entries use anchors like title29 / p_iilzI.
        # Requiring pN left 273 annotations with no highlight row at all.
        odd = self.out.execute(
            "SELECT COUNT(*) FROM highlights WHERE para_id IS NOT NULL "
            "AND para_id NOT GLOB 'p[0-9]*'").fetchone()[0]
        self.assertGreater(odd, 300)

    def test_scripture_highlights_did_not_regress(self):
        self.assertEqual(
            self.out.execute(
                "SELECT COUNT(*) FROM highlights WHERE book_id IS NOT NULL").fetchone()[0],
            9162)

    def test_every_document_annotation_has_a_document_row(self):
        orphans = self.out.execute("""
            SELECT COUNT(*) FROM annotations a WHERE a.kind = 'document'
             AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.uri = a.doc_uri)
        """).fetchone()[0]
        self.assertEqual(orphans, 0)


if __name__ == "__main__":
    unittest.main()
