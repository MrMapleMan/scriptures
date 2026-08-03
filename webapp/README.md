# Scripture Notes — offline PWA

A static, installable web app for searching and filtering Gospel Library annotations
against the full text of the standard works. No server, no network: the browser loads
one prebuilt SQLite file with [sql.js](https://sql.js.org) and does everything in memory.

```
webapp/
  build_data.py       merges the two source databases into app/data/app.sqlite
  serve.sh            builds (if needed) and serves app/ on http://localhost:8000
  app/                the PWA itself — static files, deployable anywhere
    index.html
    app.js            loading, search, filtering, rendering, chapter reader
    styles.css        light/dark theme
    service-worker.js caches the shell + dataset for offline use
    manifest.json
    vendor/           sql-wasm.js / sql-wasm.wasm
    data/app.sqlite   generated, gitignored (~18 MB)
```

## Build the dataset

```sh
python3 build_data.py \
  --verses ../scripture_text.db \
  --annotations ../resources/annotations/scripture_annotations_20260802.sqlite
```

Re-run this whenever you export fresh annotations, then bump `CACHE` in
`app/service-worker.js` so installed clients pick up the new data.

## Run

```sh
./serve.sh          # http://localhost:8000
```

Any static host works. The service worker needs `https://` or `localhost`.

## How the source data is interpreted

**Annotation URIs.** `/scriptures/<volume>/<book>/<chapter>` identifies the chapter.
Highlight URIs add a paragraph suffix — `/scriptures/bofm/alma/27.p4` — and the `p`
number is the verse number. This holds for 9,162 of 9,164 highlight targets in the
current export.

**Highlight offsets are word offsets, not character offsets.** `OffsetStart` /
`OffsetEnd` are 1-based inclusive word indexes into the rendered verse; `-1` means
"run to the start / end of the verse". Reading them as character offsets produces
mid-word garbage. About 18% of bounded highlights overshoot the verse's word count by
one to five words — the export's tokenization differs slightly from ours — so
`build_data.py` clamps them to the verse. In practice those render as
"highlighted through the end of the verse", which is what they were.

**What gets dropped.** Annotations pointing at content outside the scripture text
(general conference, manuals, Ensign, church history, and also JST, Bible Dictionary,
Guide to the Scriptures, Official Declarations, and the proclamations — none of which
are in `scripture_text.db`) are dropped *unless they carry a note*. Anything with a
note survives as a searchable note/journal entry with no verse attached. From the
2026-08-02 export: 5,721 scripture annotations + 747 notes kept, 3,005 dropped.

**Tags.** Tag names live only inside the `Content` JSON blob (`Tags` array). The
`TagsIds` column is not a reliable parallel array — 140 rows disagree on length — so
names are the source of truth and ids are ignored. 1,994 distinct tags.

## Using it

- **Search** the search box matches plain text by default; tick **Regex** for a full
  JavaScript regular expression, **Aa** for case sensitivity. Scope it to **Notes**,
  **Scripture** text, or **Both**. Matches are highlighted in the results.
- **Filters** narrow by volume, book, content type, and one or more tags
  (**Any** = union, **All** = intersection). Tags on a result card are clickable.
- **Click a reference** to open the whole chapter with every highlight in place; the
  annotation's own verses are tinted.
- `/` focuses the search box, `Esc` closes the reader.
