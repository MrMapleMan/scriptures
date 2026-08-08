#!/usr/bin/env python3
"""Anchored offline archive for General Conference, from a local talk corpus.

A local scrape of conference talks stores plain text with no paragraph ids,
while annotations address paragraphs only by id -- so the corpus cannot resolve
an anchor on its own. Aligning its paragraph *sequence* against fetched content
recovers the mapping (measured at 99.9% over 242 annotated talks), and once the
mapping is stored the corpus can regenerate paragraph text forever without the
network.

Two modes:

    --learn     fetch each talk once, align, verify, store the map, write cache
                documents. Needs the network.
    (default)   regenerate cache documents from the corpus using the stored map.
                Needs no network at all.

The corpus lives outside the repo, so --corpus defaults to absent and every
mode reports "unavailable" rather than failing when it is missing.

    python3 tools/build_alignment.py --corpus /path/conference_talks.db \\
        --annotations ../resources/annotations/<export>.sqlite --learn
"""

import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gospel_content import (
    CONTENT_API,
    GC_PREFIX,
    HIGHLIGHT_URI,
    extract_paragraphs,
    norm_text,
    write_cache,
)
MAP_NAME = "gc-alignment.json"


def corpus_talks(path):
    """uri -> (paragraph list, speaker, calling) from the local scrape."""
    # The corpus commonly lives under a path with spaces; quote it properly
    # rather than patching one character, or a '#' or '?' silently truncates it.
    con = sqlite3.connect(
        "file:%s?mode=ro" % urllib.parse.quote(os.path.abspath(path)), uri=True)
    talks = {}
    for talk, speaker, calling, url in con.execute(
            "SELECT talk, speaker, calling, url FROM talks"):
        match = re.search(r"/study(/general-conference/[^?]+)", url or "")
        if not match:
            continue
        paras = [norm_text(p) for p in (talk or "").split("\n") if norm_text(p)]
        talks[match.group(1)] = (paras, norm_text(speaker), norm_text(calling))
    con.close()
    return talks


def wanted_anchors(ann_db):
    """uri -> {para_id} for every General Conference annotation."""
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(ann_db), uri=True)
    want = {}
    for uri, raw in con.execute(
            "SELECT Uri, Highlights FROM AnnotationStorage WHERE Uri LIKE ?", (GC_PREFIX + "%",)):
        try:
            entries = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            entries = []
        for entry in entries or []:
            match = HIGHLIGHT_URI.match(entry.get("Uri") or "")
            if match and match.group(1).startswith(GC_PREFIX):
                want.setdefault(match.group(1), set()).add(match.group(2))
    con.close()
    return want


def align(api_paras, corpus_paras, speaker, calling):
    """Map para_id -> corpus index. -1/-2 mean 'the speaker/calling column'.

    Sequence alignment, not positional: the live page's ids are non-contiguous
    and non-monotonic, so comparing id number against list position measures id
    numbering rather than content.
    """
    matcher = difflib.SequenceMatcher(None, [p["text"] for p in api_paras],
                                      corpus_paras, autojunk=False)
    mapping = {}
    for op, i1, i2, j1, _j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                mapping[api_paras[i1 + k]["para_id"]] = j1 + k
    # Older markup numbers the byline and calling as p1/p2; the scraper moved
    # them into their own columns, so they are absent from the paragraph text.
    by_id = {p["para_id"]: p["text"] for p in api_paras}
    if "p1" not in mapping and speaker and by_id.get("p1") == speaker:
        mapping["p1"] = -1
    if "p2" not in mapping and calling and by_id.get("p2") == calling:
        mapping["p2"] = -2
    return mapping, matcher.ratio()


def corpus_text(mapping, para_id, paras, speaker, calling):
    idx = mapping.get(para_id)
    if idx is None:
        return None
    if idx == -1:
        return speaker
    if idx == -2:
        return calling
    return paras[idx] if 0 <= idx < len(paras) else None


def write_fetched(cache_dir, uri, payload, api_paras, needed):
    """Cache the live page for a talk whose corpus alignment was rejected.

    Stores the whole talk: this is a General Conference URI by construction, and
    the live page is present, so R15a's `fetched` case applies in full. `needed`
    is retained only to report whether the anchors the annotations want are
    actually present.
    """
    rows = [{"para_id": p["para_id"], "pid": p.get("pid"),
             "sort": p["sort"], "text": p["text"]}
            for p in api_paras]
    if not rows:
        return False
    absent = needed - {r["para_id"] for r in rows}
    if absent:
        # Not fatal: the runtime still resolves these by Pid, and the reader has
        # a notice for anchors the current revision dropped. Worth saying, since
        # it means this talk's highlights will not all land.
        print("    note: %d anchor(s) not on the live page (%s)"
              % (len(absent), ", ".join(sorted(absent)[:4])))
    canonical = payload.get("meta", {}).get("canonicalUrl")
    write_cache(cache_dir, {
        "uri": uri,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonical_url": ("https://www.churchofjesuschrist.org/study" + canonical)
                         if canonical else None,
        "restricted": bool(payload.get("restricted")),
        # The live page, not a reconstruction -- so it carries no archive label.
        "source": "fetched",
        "paragraphs": rows,
    })
    return True


def fetch(uri, timeout=30):
    req = urllib.request.Request(CONTENT_API + uri, headers={"User-Agent": "scripture-notes/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", default=os.environ.get("CONFERENCE_CORPUS"),
                        help="path to conference_talks.db (default: $CONFERENCE_CORPUS)")
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--cache", default=os.path.join(here, ".cache", "documents"))
    parser.add_argument("--maps", default=os.path.join(here, ".cache", "alignment"))
    parser.add_argument("--learn", action="store_true",
                        help="fetch and align (needs network); otherwise replay a stored map")
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if not args.corpus or not os.path.exists(args.corpus):
        print("conference corpus unavailable (%s) -- nothing to do."
              % (args.corpus or "no --corpus given, $CONFERENCE_CORPUS unset"))
        print("This feature is optional; the app works without it.")
        return 0

    talks = corpus_talks(args.corpus)
    want = wanted_anchors(args.annotations)
    targets = sorted(u for u in want if u in talks)
    if args.limit:
        targets = targets[:args.limit]
    print("corpus talks %d | annotated GC docs %d | usable %d"
          % (len(talks), len(want), len(targets)))

    map_path = os.path.join(args.maps, MAP_NAME)
    stored = {}
    if os.path.exists(map_path):
        with open(map_path, encoding="utf-8") as f:
            stored = json.load(f).get("documents", {})

    written = verified = rejected = failed = 0

    for uri in targets:
        paras, speaker, calling = talks[uri]
        needed = want[uri]

        if args.learn:
            try:
                payload = fetch(uri)
            except Exception as err:                      # noqa: BLE001 - report and continue
                failed += 1
                print("  fetch failed %s: %s" % (uri, type(err).__name__))
                continue
            time.sleep(args.delay)
            api_paras = extract_paragraphs(payload.get("content", {}).get("body", ""))
            mapping, ratio = align(api_paras, paras, speaker, calling)
            # Verification gate: a partial map is discarded rather than stored,
            # so a half-aligned talk can never render highlights in the wrong place.
            if not needed.issubset(mapping.keys()):
                rejected += 1
                print("  rejected %s (%d/%d anchors, ratio %.3f)"
                      % (uri, len(needed & mapping.keys()), len(needed), ratio))
                # The map is discarded, but the page we just fetched is not: it
                # is the live text, which is strictly better than the corpus
                # reconstruction this talk failed to earn. Throwing it away left
                # these talks with no content at all despite a successful fetch.
                if write_fetched(args.cache, uri, payload, api_paras, needed):
                    written += 1
                continue
            verified += 1
            canonical = payload.get("meta", {}).get("canonicalUrl")
            stored[uri] = {
                "map": mapping,
                "ratio": round(ratio, 4),
                # Kept so replay can reproduce document order and preserve the
                # stable Pid anchor without needing the network again.
                "order": {p["para_id"]: p["sort"] for p in api_paras},
                "pids": {p["para_id"]: p["pid"] for p in api_paras if p.get("pid")},
                "canonical_url": ("https://www.churchofjesuschrist.org/study" + canonical)
                                 if canonical else None,
            }
        else:
            entry = stored.get(uri)
            if not entry:
                continue
            mapping = {k: v for k, v in entry["map"].items()}

        entry = stored.get(uri, {})
        pids = entry.get("pids") or {}
        order_of = entry.get("order") or {}
        rows = []
        # Order by the document position recorded when the map was learned, not
        # by the number inside the id -- ids are non-contiguous and
        # non-monotonic, so sorting on them reorders the talk.
        # Every *mapped* paragraph, not only the annotated ones: this is a GC
        # talk, so R15 stores the whole thing. The map is the hard bound -- a
        # corpus paragraph the alignment never resolved has no para_id of its
        # own, and inventing one would put text under an id the live page uses
        # for something else. So an archive talk stores a superset of the
        # anchors and may still be a subset of the talk.
        for para_id in sorted(mapping, key=lambda p: order_of.get(p, 1 << 30)):
            text = corpus_text(mapping, para_id, paras, speaker, calling)
            if text:
                rows.append({"para_id": para_id, "pid": pids.get(para_id),
                             "sort": order_of.get(para_id, len(rows)), "text": text})
        if not rows:
            continue
        write_cache(args.cache, {
            "uri": uri,
            "fetched_at": None,
            "canonical_url": entry.get("canonical_url"),
            "restricted": False,
            # Reconstructed from the local corpus, not the live page: the
            # wording may predate a revision, so the reader labels it.
            "source": "archive",
            "paragraphs": rows,
        })
        written += 1

    if args.learn:
        os.makedirs(args.maps, exist_ok=True)
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "documents": stored}, f, ensure_ascii=False)
        print("verified %d, rejected %d, fetch-failed %d -> %s"
              % (verified, rejected, failed, map_path))
    print("wrote %d cache document(s) to %s" % (written, args.cache))
    print("rebuild to embed them: python3 build_data.py --annotations <export>.sqlite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
