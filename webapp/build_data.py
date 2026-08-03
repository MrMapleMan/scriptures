#!/usr/bin/env python3
"""Build the single SQLite file the PWA loads in the browser.

Merges the scripture text database with the Gospel Library annotation export
into a compact, normalized database at webapp/app/data/app.sqlite.

Usage:
    python3 build_data.py \
        --verses ../scripture_text.db \
        --annotations ../resources/annotations/scripture_annotations_20260802.sqlite \
        --out app/data/app.sqlite
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, OrderedDict

# Volumes in canonical order. Anything outside this set is not scripture text
# we have, so its annotations are treated as plain notes.
VOLUME_ORDER = ["ot", "nt", "bofm", "dc-testament", "pgp"]

# /scriptures/<volume>/<book>/<chapter>
CHAPTER_URI = re.compile(r"^/scriptures/([^/]+)/([^/]+)/(\d+)$")
# /scriptures/<volume>/<book>/<chapter>.p<verse>  -- the "p" number is the verse
HIGHLIGHT_URI = re.compile(r"^/scriptures/([^/]+)/([^/]+)/(\d+)\.p(\d+)$")

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v\xa0]+")

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

CREATE TABLE annotations (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,          -- 'scripture' | 'note'
    type          TEXT,                   -- highlight | journal | reference
    uri           TEXT,
    item_title    TEXT,                   -- volume name, e.g. "Book of Mormon"
    location      TEXT,                   -- human reference, e.g. "Alma 27:4"
    book_id       INTEGER REFERENCES books(id),
    chapter       INTEGER,
    verse_start   INTEGER,
    verse_end     INTEGER,
    note_title    TEXT,
    note_html     TEXT,
    note_text     TEXT,                   -- note_html with markup stripped
    verse_text    TEXT,                   -- text of the verses this annotation touches
    colors        TEXT,                   -- comma-separated distinct highlight colors
    tags          TEXT,                   -- comma-separated tag names (display + quick scan)
    refs_json     TEXT,
    created       TEXT,
    updated       TEXT,
    sort_date     TEXT
);
CREATE INDEX annotations_book ON annotations(book_id, chapter);
CREATE INDEX annotations_kind ON annotations(kind);
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

-- One row per highlighted verse. word_start/word_end are 1-based inclusive
-- word indexes into verses.text, already clamped to the verse's word count.
-- A row covering the whole verse has word_start = 1 and word_end = word count.
CREATE TABLE highlights (
    annotation_id TEXT NOT NULL REFERENCES annotations(id),
    book_id       INTEGER NOT NULL REFERENCES books(id),
    chapter       INTEGER NOT NULL,
    verse         INTEGER NOT NULL,
    word_start    INTEGER NOT NULL,
    word_end      INTEGER NOT NULL,
    color         TEXT,
    style         TEXT
);
CREATE INDEX highlights_ref ON highlights(book_id, chapter, verse);
CREATE INDEX highlights_ann ON highlights(annotation_id);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def strip_html(html):
    """Turn the Gospel Library note markup into readable plain text."""
    if not html:
        return ""
    text = html.replace("\r\n", "\n")
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


def parse_highlights(raw, book_ids, verse_text):
    """Return (per-verse highlight rows, touched verses, colors) for one annotation.

    Highlight offsets are 1-based inclusive *word* indexes into the rendered
    verse; -1 means "run to the start/end of the verse". A minority of exports
    overshoot the verse's word count by a word or two, so ends are clamped.
    """
    entries = load_json(raw, []) or []
    rows, verses, colors = [], [], []
    for entry in entries:
        uri = entry.get("Uri") or ""
        match = HIGHLIGHT_URI.match(uri)
        if not match:
            continue
        _volume, book_url, chapter, verse = match.groups()
        chapter, verse = int(chapter), int(verse)
        text = verse_text.get((book_url, chapter, verse))
        if text is None:
            continue  # verse outside the scripture text we have

        word_count = len(text.split())
        start = entry.get("OffsetStart", -1)
        end = entry.get("OffsetEnd", -1)
        start = 1 if start in (-1, None) else max(1, min(int(start), word_count))
        end = word_count if end in (-1, None) else max(1, min(int(end), word_count))
        if end < start:
            start, end = end, start

        color = entry.get("Color") or "yellow"
        rows.append((book_ids[book_url], chapter, verse, start, end, color,
                     entry.get("Style") or None))
        verses.append((book_url, chapter, verse, text))
        colors.append(color)
    return rows, verses, colors


def build_annotations(ann, out, book_ids, verse_text):
    counts = Counter()
    tag_counts = Counter()
    ann_rows, tag_rows, hl_rows = [], [], []

    query = """
        SELECT AnnotationId, Type, Uri, ItemTitle, Location, NoteTitle, NoteContent,
               Highlights, Refs, Content, Created, Timestamp
        FROM AnnotationStorage
    """
    for (aid, atype, uri, item_title, location, note_title, note_html,
         highlights, refs, content, created, timestamp) in ann.execute(query):
        uri = uri or ""
        note_title = (note_title or "").strip()
        note_text = strip_html(note_html)
        has_note = bool(note_title or note_text)

        chapter_match = CHAPTER_URI.match(uri)
        book_url = chapter_match.group(2) if chapter_match else None
        is_scripture = bool(chapter_match) and book_url in book_ids

        hl, touched, colors = ([], [], [])
        if is_scripture:
            hl, touched, colors = parse_highlights(highlights, book_ids, verse_text)
            if not hl:
                # Chapter is ours but every highlight target is (e.g.) a chapter
                # heading or study summary -- keep it only if it carries a note.
                is_scripture = False

        if not is_scripture and not has_note:
            counts["dropped"] += 1
            continue

        # Tag names live only in the Content blob; TagsIds is unreliable
        # (140 rows disagree on length), so names are the source of truth.
        tags = [t.strip() for t in (load_json(content, {}) or {}).get("Tags", []) or [] if t.strip()]
        tags = list(OrderedDict.fromkeys(tags))

        if is_scripture:
            kind = "scripture"
            book_id = book_ids[book_url]
            chapter = int(chapter_match.group(3))
            verse_numbers = sorted({v for _b, _c, v, _t in touched})
            verse_start, verse_end = verse_numbers[0], verse_numbers[-1]
            seen = OrderedDict((v, t) for _b, _c, v, t in sorted(touched, key=lambda r: r[2]))
            joined_verses = "\n".join(seen.values())
            hl_rows.extend((aid,) + row for row in hl)
        else:
            kind = "note"
            book_id = chapter = verse_start = verse_end = None
            joined_verses = ""

        counts[kind] += 1
        sort_date = timestamp or created or ""
        ann_rows.append((
            aid, kind, atype, uri or None, item_title, location,
            book_id, chapter, verse_start, verse_end,
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
        INSERT INTO annotations (id, kind, type, uri, item_title, location, book_id, chapter,
                                 verse_start, verse_end, note_title, note_html, note_text,
                                 verse_text, colors, tags, refs_json, created, updated, sort_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ann_rows)
    out.executemany("INSERT INTO annotation_tags (annotation_id, tag) VALUES (?, ?)", tag_rows)
    out.executemany("INSERT INTO tags (name, count) VALUES (?, ?)", sorted(tag_counts.items()))
    out.executemany("""
        INSERT INTO highlights (annotation_id, book_id, chapter, verse, word_start, word_end,
                                color, style)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, hl_rows)
    counts["tags"] = len(tag_counts)
    counts["highlighted_verses"] = len(hl_rows)
    return counts


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

    counts = build_annotations(ann, out, book_ids, verse_text)
    print("annotations: %d on scripture, %d notes, %d dropped (no note, not scripture)"
          % (counts["scripture"], counts["note"], counts["dropped"]))
    print("            %d highlighted verses, %d distinct tags"
          % (counts["highlighted_verses"], counts["tags"]))

    out.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [
        ("built_from_annotations", os.path.basename(args.annotations)),
        ("annotation_count", str(counts["scripture"] + counts["note"])),
        ("dropped_count", str(counts["dropped"])),
        ("tag_count", str(counts["tags"])),
    ])
    out.commit()
    out.execute("VACUUM")
    out.close()
    print("wrote %s (%.1f MB)" % (out_path, os.path.getsize(out_path) / 1e6))


if __name__ == "__main__":
    main()
