#!/usr/bin/env python3
"""Decide the word-offset convention for non-scripture highlights.

Scripture offsets need a -1 shift because Gospel Library prints the verse
number as word 1 of the paragraph. A talk paragraph has no leading number, so
that rationale does not transfer -- but "probably not" is not a basis for
tinting the wrong words, so this measures it the same way the scripture
convention was originally settled.

Method (same as the README's 38.7%/62.1% scripture table): for every fully
bounded highlight, apply a candidate shift and count how often the span's
boundaries land on a clause boundary. Only interior boundaries score -- a span
running to the edge of the paragraph earns nothing either way -- so a
convention that is off by one shows up as a collapse in the hit rate.

Needs paragraph text, so run it after the cache has been filled:
    python3 tools/measure_offsets.py --annotations ../resources/annotations/<export>.sqlite
"""

import argparse
import json
import os
import random
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gospel_content import CHAPTER_URI, HIGHLIGHT_URI, read_cache

CLAUSE_END = re.compile(r"[.,;:!?—–)\"”’]$")
OPENS = re.compile(r"^[(\"“‘]")


def bounded_highlights(ann_db, cache):
    """Every non-scripture highlight with both bounds set, paired with its text."""
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(ann_db), uri=True)
    out = []
    for uri, raw in con.execute(
            "SELECT Uri, Highlights FROM AnnotationStorage WHERE Highlights IS NOT NULL"):
        if not uri or CHAPTER_URI.match(uri):
            continue
        try:
            entries = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for entry in entries or []:
            match = HIGHLIGHT_URI.match(entry.get("Uri") or "")
            if not match:
                continue
            doc = cache.get(match.group(1))
            if not doc:
                continue
            para = next((p for p in doc["paragraphs"] if p["para_id"] == match.group(2)), None)
            if not para:
                continue
            start, end = entry.get("OffsetStart", -1), entry.get("OffsetEnd", -1)
            if start in (-1, None) or end in (-1, None):
                continue
            out.append((int(start), int(end), para["text"].split()))
    con.close()
    return out


def score(samples, shift):
    """Clean interior starts / ends for a candidate shift."""
    starts = ends = start_n = end_n = 0
    for raw_start, raw_end, words in samples:
        n = len(words)
        if n < 3:
            continue
        s = raw_start - shift
        e = raw_end - shift
        if not (1 <= s <= n and 1 <= e <= n and s <= e):
            continue
        if s > 1:                      # interior start only
            start_n += 1
            prev = words[s - 2]
            if CLAUSE_END.search(prev) or OPENS.match(words[s - 1]):
                starts += 1
        if e < n:                      # interior end only
            end_n += 1
            if CLAUSE_END.search(words[e - 1]):
                ends += 1
    return (starts, start_n, ends, end_n)


def random_baseline(samples, trials=3):
    """What the same metric scores on spans of the same length placed at random."""
    rng = random.Random(17)
    hits = [0, 0, 0, 0]
    for _ in range(trials):
        fake = []
        for raw_start, raw_end, words in samples:
            width = max(0, raw_end - raw_start)
            n = len(words)
            if n < 3:
                continue
            s = rng.randint(1, max(1, n - width))
            fake.append((s, min(n, s + width), words))
        got = score(fake, 0)
        for i in range(4):
            hits[i] += got[i]
    return tuple(h // trials for h in hits)


def pct(hit, total):
    return "n/a" if not total else "%.1f%%" % (100.0 * hit / total)


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--cache", default=os.path.join(here, ".cache", "documents"))
    args = parser.parse_args()

    cache = read_cache(args.cache)
    if not cache:
        sys.exit("content cache is empty (%s) -- browse the app first so paragraphs exist"
                 % args.cache)

    samples = bounded_highlights(args.annotations, cache)
    print("fully bounded non-scripture highlights with text: %d" % len(samples))
    if len(samples) < 50:
        print("WARNING: too few samples to decide; fill the cache further before trusting this")

    print()
    print("%-28s %-22s %s" % ("convention", "clean interior starts", "clean interior ends"))
    rows = []
    for label, shift in (("offsets read directly (0)", 0), ("offset - 1", 1), ("offset - 2", 2)):
        s_hit, s_n, e_hit, e_n = score(samples, shift)
        rows.append((label, shift, s_hit, s_n, e_hit, e_n))
        print("%-28s %-22s %s" % (label, pct(s_hit, s_n), pct(e_hit, e_n)))
    r = random_baseline(samples)
    print("%-28s %-22s %s" % ("random spans", pct(r[0], r[1]), pct(r[2], r[3])))

    best = max(rows, key=lambda row: ((row[2] / row[3] if row[3] else 0)
                                      + (row[4] / row[5] if row[5] else 0)))
    print()
    print("best by combined clause-boundary rate: shift = %d" % best[1])
    print("Set DOCUMENT_OFFSET_SHIFT in build_data.py to this value, record the table in")
    print("webapp/README.md, and rebuild. If the top two are within noise, prefer shift = 0:")
    print("the verse-number rationale behind the scripture -1 does not apply to paragraphs.")


if __name__ == "__main__":
    main()
