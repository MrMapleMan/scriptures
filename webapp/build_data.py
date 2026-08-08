#!/usr/bin/env python3
"""Build the single SQLite file the PWA loads in the browser.

Merges the scripture text database with the Gospel Library annotation export
into a compact, normalized database at webapp/app/data/app.sqlite.

Annotations that point outside the bundled scripture text -- conference talks,
manuals, magazines, church history -- are retained as `document` rows. Their
paragraph text is embedded when it is present in the local content cache
(webapp/.cache/documents/), which the app fills as you browse. This build never
touches the network: a document missing from the cache is kept with
fetch_state='unfetched' and its annotations are retained regardless.

Usage:
    python3 build_data.py \
        --verses ../scripture_text.db \
        --annotations ../resources/annotations/scripture_annotations_20260802.sqlite
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, OrderedDict

from gospel_content import (
    BUCKETS,
    CHAPTER_URI,
    HIGHLIGHT_URI,
    VERSE_ANCHOR,
    classify,
    read_cache,
    stores_whole_document,
)

# Volumes in canonical order. Anything outside this set is not scripture text
# we have, so its annotations are treated as documents or plain notes.
VOLUME_ORDER = ["ot", "nt", "bofm", "dc-testament", "pgp"]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v\xa0]+")

# Scripture word offsets are shifted by -1 because Gospel Library prints the
# verse number as word 1 of the paragraph.
VERSE_OFFSET_SHIFT = 1

# A talk paragraph has no leading verse number, so that rationale does not
# apply and the correct shift is an open measurement (tools/measure_offsets.py).
# Until it is decided, document highlights render as whole paragraphs rather
# than guessing a partial span -- a wrong shift silently tints the wrong words.
DOCUMENT_OFFSET_SHIFT = None

SCHEMA = """
PRAGMA journal_mode = OFF;

CREATE TABLE volumes (
    id     INTEGER PRIMARY KEY,
    url    TEXT NOT NULL UNIQUE,
    title  TEXT NOT NULL,
    sort   INTEGER NOT NULL
);

CREATE TABLE books (
    id          INTEGER PRIMARY KEY,
    volume_id   INTEGER NOT NULL REFERENCES volumes(id),
    url         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    long_title  TEXT,
    sort        INTEGER NOT NULL
);

CREATE TABLE verses (
    id       INTEGER PRIMARY KEY,
    book_id  INTEGER NOT NULL REFERENCES books(id),
    chapter  INTEGER NOT NULL,
    verse    INTEGER NOT NULL,
    text     TEXT NOT NULL
);
CREATE UNIQUE INDEX verses_ref ON verses(book_id, chapter, verse);

-- Non-scripture sources an annotation points at. A row exists whether or not
-- its text has been fetched, so a card can always be rendered from metadata.
CREATE TABLE documents (
    uri           TEXT PRIMARY KEY,
    category      TEXT NOT NULL,
    raw_category  TEXT,
    title         TEXT,
    subtitle      TEXT,
    item_title    TEXT,
    canonical_url TEXT,
    fetch_state   TEXT NOT NULL,   -- cached | empty | failed | unfetched
    fetch_error   TEXT,
    fetched_at    TEXT,
    source        TEXT,             -- 'fetched' (live page) | 'archive' (local corpus)
    restricted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX documents_category ON documents(category);

-- Only paragraphs an annotation actually references. `sort` is DOM position,
-- not the number in para_id: ids are non-contiguous and non-monotonic.
CREATE TABLE paragraphs (
    doc_uri  TEXT NOT NULL REFERENCES documents(uri),
    para_id  TEXT NOT NULL,
    pid      TEXT,
    sort     INTEGER NOT NULL,
    text     TEXT NOT NULL
);
CREATE UNIQUE INDEX paragraphs_ref ON paragraphs(doc_uri, para_id);
CREATE INDEX paragraphs_pid ON paragraphs(doc_uri, pid);

CREATE TABLE annotations (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,          -- 'scripture' | 'document' | 'note'
    category      TEXT NOT NULL,          -- content-type bucket
    type          TEXT,                   -- highlight | journal | reference
    uri           TEXT,
    doc_uri       TEXT REFERENCES documents(uri),
    item_title    TEXT,
    location      TEXT,
    subtitle      TEXT,
    book_id       INTEGER REFERENCES books(id),
    chapter       INTEGER,
    verse_start   INTEGER,
    verse_end     INTEGER,
    note_title    TEXT,
    note_html     TEXT,
    note_text     TEXT,
    verse_text    TEXT,
    colors        TEXT,
    tags          TEXT,                   -- display only; 322 tag names contain
                                          -- ", " -- read annotation_tags instead
    refs_json     TEXT,
    created       TEXT,
    updated       TEXT,
    sort_date     TEXT
);
CREATE INDEX annotations_book ON annotations(book_id, chapter);
CREATE INDEX annotations_kind ON annotations(kind);
CREATE INDEX annotations_category ON annotations(category);
CREATE INDEX annotations_doc ON annotations(doc_uri);
CREATE INDEX annotations_sort ON annotations(sort_date DESC);

CREATE TABLE annotation_tags (
    annotation_id TEXT NOT NULL REFERENCES annotations(id),
    tag           TEXT NOT NULL
);
CREATE INDEX annotation_tags_tag ON annotation_tags(tag);
CREATE INDEX annotation_tags_ann ON annotation_tags(annotation_id);

CREATE TABLE tags (
    name  TEXT PRIMARY KEY,
    count INTEGER NOT NULL
);

-- One row per highlighted verse or paragraph. Scripture rows carry
-- (book_id, chapter, verse); document rows carry (doc_uri, para_id, pid).
-- word_start/word_end are 1-based inclusive word indexes, already clamped.
CREATE TABLE highlights (
    annotation_id TEXT NOT NULL REFERENCES annotations(id),
    book_id       INTEGER REFERENCES books(id),
    chapter       INTEGER,
    verse         INTEGER,
    doc_uri       TEXT REFERENCES documents(uri),
    para_id       TEXT,
    pid           TEXT,
    word_start    INTEGER,
    word_end      INTEGER,
    color         TEXT,
    style         TEXT
);
CREATE INDEX highlights_ref ON highlights(book_id, chapter, verse);
CREATE INDEX highlights_ann ON highlights(annotation_id);
CREATE INDEX highlights_doc ON highlights(doc_uri, para_id);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def strip_html(html_text):
    """Turn the Gospel Library note markup into readable plain text.

    Distinct from gospel_content.norm_text: notes keep their line structure and
    bullets because they are displayed as written, whereas paragraph text is
    collapsed for comparison and inline rendering.
    """
    if not html_text:
        return ""
    text = html_text.replace("\r\n", "\n")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*(div|p|li|h[1-6]|tr)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<\s*li[^>]*>", "• ", text, flags=re.I)
    text = TAG_RE.sub("", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    text = WS_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def load_json(raw, default=None):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def clamp_span(start, end, word_count, shift):
    """Map Gospel Library word offsets onto a 1-based inclusive span.

    -1 (or missing) means run to the start/end. Out-of-range bounds are
    clamped and a reversed pair is swapped rather than dropped -- the export's
    tokenisation differs from whitespace splitting in a few places, so an
    occasional highlight really is a word off at one end.
    """
    if word_count <= 0:
        return None
    if start in (-1, None):
        start = 1
    else:
        start = max(1, min(int(start) - shift, word_count))
    if end in (-1, None):
        end = word_count
    else:
        end = max(1, min(int(end) - shift, word_count))
    if end < start:
        start, end = end, start
    return start, end


def build_scriptures(src, out):
    """Copy volumes/books/verses across, normalized and stripped of dead columns."""
    rows = src.execute("""
        SELECT volume_lds_url, volume_title, book_lds_url, book_title, book_long_title,
               CAST(chapter_number AS INTEGER), CAST(verse_number AS INTEGER), scripture_text,
               rowid
        FROM verses
        ORDER BY rowid
    """).fetchall()

    volumes = OrderedDict()
    books = OrderedDict()
    for vurl, vtitle, burl, btitle, blong, chapter, verse, text, _rowid in rows:
        if vurl not in volumes:
            sort = VOLUME_ORDER.index(vurl) if vurl in VOLUME_ORDER else 99
            volumes[vurl] = (len(volumes) + 1, vtitle, sort)
        if burl not in books:
            books[burl] = (len(books) + 1, volumes[vurl][0], btitle, blong, len(books))

    out.executemany("INSERT INTO volumes (id, url, title, sort) VALUES (?, ?, ?, ?)",
                    [(vid, url, title, sort) for url, (vid, title, sort) in volumes.items()])
    out.executemany(
        "INSERT INTO books (id, volume_id, url, title, long_title, sort) VALUES (?, ?, ?, ?, ?, ?)",
        [(bid, vid, url, title, long, sort) for url, (bid, vid, title, long, sort) in books.items()])

    verse_rows = []
    verse_text = {}
    for vurl, _vt, burl, _bt, _bl, chapter, verse, text, _rowid in rows:
        bid = books[burl][0]
        verse_rows.append((bid, chapter, verse, text))
        verse_text[(burl, chapter, verse)] = text
    out.executemany("INSERT INTO verses (book_id, chapter, verse, text) VALUES (?, ?, ?, ?)",
                    verse_rows)

    book_ids = {url: meta[0] for url, meta in books.items()}
    return book_ids, verse_text


def parse_verse_highlights(raw, book_ids, verse_text):
    """Return (rows, touched verses, colors) for a scripture annotation.

    Highlight offsets are inclusive *word* indexes into the paragraph as Gospel
    Library renders it, which puts the verse number in front of the text as word
    1. So verse-text word == offset - 1. Scored against 665 fully bounded
    highlights, this convention lands a clause boundary at 39% of interior
    starts and 62% of interior ends, versus 9%/12% for reading the offsets
    directly and ~13%/19% for random spans.
    """
    entries = load_json(raw, []) or []
    rows, verses, colors = [], [], []
    for entry in entries:
        match = HIGHLIGHT_URI.match(entry.get("Uri") or "")
        if not match:
            continue
        chapter_match = CHAPTER_URI.match(match.group(1))
        if not chapter_match:
            continue
        # Only 'pN' names a verse. A chapter heading or study summary anchor
        # (title3, study_summary1) lives in the same namespace but has no verse.
        verse_match = VERSE_ANCHOR.match(match.group(2))
        if not verse_match:
            continue
        _volume, book_url, chapter = chapter_match.groups()
        verse = int(verse_match.group(1))
        chapter = int(chapter)
        text = verse_text.get((book_url, chapter, verse))
        if text is None:
            continue  # verse outside the scripture text we have

        span = clamp_span(entry.get("OffsetStart", -1), entry.get("OffsetEnd", -1),
                          len(text.split()), VERSE_OFFSET_SHIFT)
        if span is None:
            continue
        color = entry.get("Color") or "yellow"
        rows.append((book_ids[book_url], chapter, verse, span[0], span[1], color,
                     entry.get("Style") or None))
        verses.append((book_url, chapter, verse, text))
        colors.append(color)
    return rows, verses, colors


def parse_document_highlights(raw, doc_uri, paragraphs):
    """Return (rows, colors) for a non-scripture annotation.

    Anchors on Pid (the page's data-aid) first and para_id second: Pid is stable
    across content revisions while paragraph numbering is not, so a talk that
    gets re-flowed keeps its highlights.
    """
    entries = load_json(raw, []) or []
    by_para = {p["para_id"]: p for p in paragraphs}
    by_pid = {p["pid"]: p for p in paragraphs if p.get("pid")}
    rows, colors = [], []
    for entry in entries:
        match = HIGHLIGHT_URI.match(entry.get("Uri") or "")
        if not match or match.group(1) != doc_uri:
            continue
        para_id = match.group(2)
        pid = entry.get("Pid")
        para = by_pid.get(pid) or by_para.get(para_id)
        color = entry.get("Color") or "yellow"

        if para is None:
            # No text yet (uncached document, or a revised page that dropped the
            # anchor). Keep the row so the reader can say what is missing.
            rows.append((doc_uri, para_id, pid, None, None, color,
                         entry.get("Style") or None))
            colors.append(color)
            continue

        word_count = len(para["text"].split())
        if DOCUMENT_OFFSET_SHIFT is None:
            span = (1, word_count) if word_count else None
        else:
            span = clamp_span(entry.get("OffsetStart", -1), entry.get("OffsetEnd", -1),
                              word_count, DOCUMENT_OFFSET_SHIFT)
        rows.append((doc_uri, para["para_id"], para.get("pid"),
                     span[0] if span else None, span[1] if span else None,
                     color, entry.get("Style") or None))
        colors.append(color)
    return rows, colors


def referenced_anchors(ann):
    """doc_uri -> (anchor ids, Pids) some annotation actually highlights.

    A cache document holds the whole page, but only the paragraphs an
    annotation points at are worth embedding; keeping the rest would multiply
    the dataset by the length of every talk and manual chapter. Collected in a
    pre-pass because a document's row is written when its first annotation is
    seen, before the others have been read.

    Both keys are needed: when a page has been renumbered, the paragraph is
    found by Pid and its current para_id is not the one the annotation records.
    """
    wanted = {}
    for uri, highlights in ann.execute(
            "SELECT Uri, Highlights FROM AnnotationStorage WHERE Highlights IS NOT NULL"):
        for entry in load_json(highlights, []) or []:
            match = HIGHLIGHT_URI.match(entry.get("Uri") or "")
            if not match:
                continue
            anchors, pids = wanted.setdefault(match.group(1), (set(), set()))
            anchors.add(match.group(2))
            if entry.get("Pid"):
                pids.add(entry["Pid"])
    return wanted


def build_annotations(ann, out, book_ids, verse_text, cache):
    counts = Counter()
    tag_counts = Counter()
    category_counts = Counter()
    ann_rows, tag_rows, hl_rows, doc_rows, para_rows = [], [], [], [], []
    seen_docs = set()
    wanted = referenced_anchors(ann)

    query = """
        SELECT AnnotationId, Type, Uri, ItemTitle, Location, SubLocation, CategoryName,
               NoteTitle, NoteContent, Highlights, Refs, Content, Created, Timestamp
        FROM AnnotationStorage
    """
    for (aid, atype, uri, item_title, location, sub_location, category_name,
         note_title, note_html, highlights, refs, content, created, timestamp) in ann.execute(query):
        uri = uri or ""
        note_title = (note_title or "").strip()
        note_text = strip_html(note_html)
        has_note = bool(note_title or note_text)

        chapter_match = CHAPTER_URI.match(uri)
        book_url = chapter_match.group(2) if chapter_match else None
        is_scripture = bool(chapter_match) and book_url in book_ids

        hl, touched, colors = ([], [], [])
        if is_scripture:
            hl, touched, colors = parse_verse_highlights(highlights, book_ids, verse_text)
            if not hl:
                # Chapter is ours but every highlight target is (e.g.) a chapter
                # heading or study summary -- fall through to document/note.
                is_scripture = False

        doc_uri = None
        doc_hl = []
        # A URI that classifies as My Notes (/journal) names the notebook, not a
        # readable document -- giving it a reader would offer to fetch content
        # that does not exist. Everything else with a URI is a document, even
        # with no anchors: a bare reference is still worth opening.
        if not is_scripture and uri and classify(uri, category_name) != "My Notes":
            doc_uri = uri
            cached = cache.get(doc_uri)
            paragraphs = cached["paragraphs"] if cached else []
            doc_hl, colors = parse_document_highlights(highlights, doc_uri, paragraphs)

            if doc_uri not in seen_docs:
                seen_docs.add(doc_uri)
                error = cached.get("error") if cached else None
                if cached is None:
                    state, fetched_at, canonical = "unfetched", None, None
                elif error:
                    # The app records why a fetch failed so a permanently gone
                    # document (e.g. the retired Handbook 2, HTTP 404) is not
                    # retried on every build.
                    state, fetched_at = "failed", cached.get("fetched_at")
                    canonical = cached.get("canonical_url")
                elif not paragraphs:
                    state, fetched_at = "empty", cached.get("fetched_at")
                    canonical = cached.get("canonical_url")
                else:
                    state, fetched_at = "cached", cached.get("fetched_at")
                    canonical = cached.get("canonical_url")
                    # General Conference embeds the whole talk so the reader can
                    # show context around the annotation; every other namespace
                    # embeds only what an annotation points at, because the
                    # dataset ships to a phone and manual chapters are long.
                    keep, keep_pids = wanted.get(doc_uri, (set(), set()))
                    keep_all = stores_whole_document(doc_uri)
                    for p in paragraphs:
                        if (keep_all or p["para_id"] in keep
                                or (p.get("pid") and p["pid"] in keep_pids)):
                            para_rows.append((doc_uri, p["para_id"], p.get("pid"),
                                              p["sort"], p["text"]))
                doc_rows.append((doc_uri, classify(doc_uri, category_name), category_name,
                                 location, sub_location, item_title, canonical,
                                 state, error, fetched_at,
                                 (cached or {}).get("source") or "fetched",
                                 1 if (cached or {}).get("restricted") else 0))

        if not is_scripture and not doc_uri and not has_note:
            counts["dropped"] += 1
            continue

        # Tag names live only in the Content blob; TagsIds is unreliable
        # (140 rows disagree on length), so names are the source of truth.
        tags = [t.strip() for t in (load_json(content, {}) or {}).get("Tags", []) or [] if t.strip()]
        tags = list(OrderedDict.fromkeys(tags))

        if is_scripture:
            kind = "scripture"
            category = "Scriptures"
            book_id = book_ids[book_url]
            chapter = int(chapter_match.group(3))
            verse_numbers = sorted({v for _b, _c, v, _t in touched})
            verse_start, verse_end = verse_numbers[0], verse_numbers[-1]
            seen = OrderedDict((v, t) for _b, _c, v, t in sorted(touched, key=lambda r: r[2]))
            joined_verses = "\n".join(seen.values())
            hl_rows.extend((aid, r[0], r[1], r[2], None, None, None, r[3], r[4], r[5], r[6])
                           for r in hl)
        elif doc_uri:
            kind = "document"
            category = classify(doc_uri, category_name)
            book_id = chapter = verse_start = verse_end = None
            joined_verses = ""
            hl_rows.extend((aid, None, None, None, r[0], r[1], r[2], r[3], r[4], r[5], r[6])
                           for r in doc_hl)
        else:
            kind = "note"
            category = "My Notes"
            book_id = chapter = verse_start = verse_end = None
            joined_verses = ""

        counts[kind] += 1
        category_counts[category] += 1
        sort_date = timestamp or created or ""
        ann_rows.append((
            aid, kind, category, atype, uri or None, doc_uri, item_title, location,
            sub_location, book_id, chapter, verse_start, verse_end,
            note_title or None, note_html or None, note_text or None,
            joined_verses or None,
            ",".join(list(OrderedDict.fromkeys(colors))) or None,
            ", ".join(tags) or None,
            refs or None, created, timestamp, sort_date,
        ))
        for tag in tags:
            tag_rows.append((aid, tag))
            tag_counts[tag] += 1

    out.executemany("""
        INSERT INTO documents (uri, category, raw_category, title, subtitle, item_title,
                               canonical_url, fetch_state, fetch_error, fetched_at, source,
                               restricted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, doc_rows)
    out.executemany("""
        INSERT INTO paragraphs (doc_uri, para_id, pid, sort, text) VALUES (?, ?, ?, ?, ?)
    """, para_rows)
    out.executemany("""
        INSERT INTO annotations (id, kind, category, type, uri, doc_uri, item_title, location,
                                 subtitle, book_id, chapter, verse_start, verse_end,
                                 note_title, note_html, note_text, verse_text, colors, tags,
                                 refs_json, created, updated, sort_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ann_rows)
    out.executemany("INSERT INTO annotation_tags (annotation_id, tag) VALUES (?, ?)", tag_rows)
    out.executemany("INSERT INTO tags (name, count) VALUES (?, ?)", sorted(tag_counts.items()))
    out.executemany("""
        INSERT INTO highlights (annotation_id, book_id, chapter, verse, doc_uri, para_id, pid,
                                word_start, word_end, color, style)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, hl_rows)
    counts["tags"] = len(tag_counts)
    counts["documents"] = len(doc_rows)
    counts["paragraphs"] = len(para_rows)
    counts["highlight_rows"] = len(hl_rows)
    return counts, category_counts


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verses", default=os.path.join(here, "..", "scripture_text.db"),
                        help="path to scripture_text.db")
    parser.add_argument("--annotations", required=True,
                        help="path to the Gospel Library annotation export (.sqlite)")
    parser.add_argument("--out", default=os.path.join(here, "app", "data", "app.sqlite"),
                        help="output database the PWA fetches")
    parser.add_argument("--cache", default=os.path.join(here, ".cache", "documents"),
                        help="local content cache the app writes back into")
    args = parser.parse_args()

    for path in (args.verses, args.annotations):
        if not os.path.exists(path):
            sys.exit("not found: %s" % path)

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)

    src = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(args.verses), uri=True)
    ann = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(args.annotations), uri=True)
    out = sqlite3.connect(out_path)
    out.executescript(SCHEMA)

    book_ids, verse_text = build_scriptures(src, out)
    print("scriptures: %d books, %d verses" % (len(book_ids), len(verse_text)))

    warnings = []
    cache = read_cache(args.cache, warn=warnings.append)
    for line in warnings:
        print("  warning: %s" % line)
    print("content cache: %d documents in %s" % (len(cache), args.cache))

    counts, category_counts = build_annotations(ann, out, book_ids, verse_text, cache)
    print("annotations: %d scripture, %d document, %d note, %d dropped (no note, no verse, no uri)"
          % (counts["scripture"], counts["document"], counts["note"], counts["dropped"]))
    with_text = out.execute(
        "SELECT COUNT(*) FROM documents WHERE fetch_state = 'cached'").fetchone()[0]
    print("            %d documents (%d with text), %d paragraphs, %d distinct tags"
          % (counts["documents"], with_text, counts["paragraphs"], counts["tags"]))
    for bucket in BUCKETS:
        if category_counts.get(bucket):
            print("            %-22s %5d" % (bucket, category_counts[bucket]))

    unfetched = out.execute(
        "SELECT COUNT(*) FROM documents WHERE fetch_state = 'unfetched'").fetchone()[0]
    if unfetched:
        print("            %d documents have no text yet -- open them in the app to fetch"
              % unfetched)

    out.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [
        ("built_from_annotations", os.path.basename(args.annotations)),
        ("annotation_count", str(counts["scripture"] + counts["document"] + counts["note"])),
        ("dropped_count", str(counts["dropped"])),
        ("tag_count", str(counts["tags"])),
        ("document_count", str(counts["documents"])),
        ("unfetched_count", str(unfetched)),
        ("document_offset_shift", "" if DOCUMENT_OFFSET_SHIFT is None
         else str(DOCUMENT_OFFSET_SHIFT)),
    ])
    out.commit()
    out.execute("VACUUM")
    out.close()
    print("wrote %s (%.1f MB)" % (out_path, os.path.getsize(out_path) / 1e6))


if __name__ == "__main__":
    main()
