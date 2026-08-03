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

**Highlight offsets are word offsets, not character offsets, and they count the
verse number.** `OffsetStart` / `OffsetEnd` are inclusive word indexes into the
paragraph *as Gospel Library renders it*, which prints the verse number ahead of the
text as word 1. So a verse-text word index is `offset - 1`. `-1` means "run to the
start / end of the verse". Reading them as character offsets produces mid-word
garbage; reading them as word indexes without the `-1` shifts every highlight one
word to the right.

The shift was established by scoring candidate conventions against the 665 fully
bounded highlights, counting how often a span boundary lands on a clause boundary
(interior boundaries only, so runs to the verse edge earn nothing):

| convention | clean interior starts | clean interior ends |
|---|---|---|
| offsets read directly | 8.9% | 12.3% |
| **`offset - 1` (used)** | **38.7%** | **62.1%** |
| `-1` start, `-2` end | 38.9% | 21.6% |
| random spans | ~13% | ~19% |

It also explains the 89 highlights whose end offset is exactly `word_count + 1`:
those simply run to the last word. After the shift, 1.1% of highlights still fall
outside their verse and are clamped — the export's tokenization differs from plain
whitespace splitting in a few places (em dashes, KJV italics), so an occasional
highlight is still a word off at one end.

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

- **Show — All / Notes / Scripture** does double duty. It always filters the list
  (All = 6,468, Notes = the 1,653 carrying a note, Scripture = the 5,721 tied to a
  verse), *and* it decides which text a search term is matched against — note text
  under Notes, verse text under Scripture, either under All.
- **Search** the search box matches plain text by default; tick **Regex** for a full
  JavaScript regular expression, **Aa** for case sensitivity. Those two only shape a
  search term, so they dim until you type one. Matches are highlighted in the results.
- **Filters** narrow by volume, book, and one or more tags. **Limit to → Note only**
  isolates the 747 entries not tied to a verse: journal entries and notes on talks or
  manuals. Tags on a result card are clickable.
- **Tag regex** is a second tag constraint, matched case-insensitively against tag
  *names*: a result is kept if it carries at least one tag matching the pattern.
  It combines with the clicked tags through the same `all`/`any` toggle — `all` ANDs
  them, `any` ORs them — and every tag it currently matches is outlined in the chip
  list. Note this is different from the box above it, which only narrows which chips
  are listed and has no effect on results.
- **The tag list follows the results.** The tag section reads *Match `all` selected
  tags*, where `all` is a button that flips to `any`. On **all** (the default) a
  result must carry every selected tag, and the chooser offers only tags found on the
  current results — so every chip narrows things further and no click can land on
  zero results. On **any** it becomes a union, and the list widens past the current
  results, since an unrelated tag would otherwise be unreachable. Selected tags stay
  listed either way, so they can always be switched off.
- **Click a reference** to open the whole chapter with every highlight in place; the
  annotation's own verses are tinted.
- `/` focuses the search box, `Esc` closes the reader.
