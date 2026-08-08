# Scripture Notes — offline PWA

A static, installable web app for searching and filtering Gospel Library annotations
against the full text of the standard works. No server, no accounts: the browser loads
one prebuilt SQLite file with [sql.js](https://sql.js.org) and does everything in memory.

Annotations on content outside the scriptures — conference talks, manuals, magazines,
church history — are kept too. Their paragraph text is fetched from the Church's own
content API the first time you open one, cached, and folded into the next build.

```
webapp/
  build_data.py       merges the source databases into app/data/app.sqlite (never uses the network)
  gospel_content.py   shared text normalisation, paragraph extraction, classification, cache I/O
  dev_server.py       serves app/ and accepts content the app writes back
  serve.sh            builds (if needed) and serves on http://localhost:8000
  tools/
    measure_offsets.py   decides the word-offset convention for non-scripture highlights
    build_alignment.py   anchored offline archive for conference talks, from a local corpus
    unpack_export.py     unpacks the app's "Export fetched content" download into the cache
  tests/              stdlib unittest; no network, no external fixtures
  .cache/documents/   fetched paragraph text (gitignored) -- grows as you browse
  app/                the PWA itself — static files, deployable anywhere
    index.html
    app.js            loading, search, filtering, rendering, readers, fetch, warming
    styles.css        light/dark theme
    service-worker.js caches the shell + dataset offline; runtime route for the content API
    manifest.json
    vendor/           sql-wasm.js / sql-wasm.wasm
    data/app.sqlite   generated, gitignored
```

## Build the dataset

```sh
python3 build_data.py \
  --verses ../scripture_text.db \
  --annotations ../resources/annotations/scripture_annotations_20260802.sqlite
```

Re-run this whenever you export fresh annotations, then bump `CACHE` in
`app/service-worker.js` so installed clients pick up the new data.

**The build never makes a network request.** It embeds whatever paragraph text is already
in `.cache/documents/`; anything missing is recorded as `unfetched` and its annotations
are kept regardless. Nothing is ever dropped because content is unavailable.

## Run

```sh
./serve.sh          # http://localhost:8000
```

`serve.sh` runs `dev_server.py`, which serves `app/` exactly like `http.server` did and
additionally accepts `POST /_cache/<sha256>` so content the app fetches lands in
`.cache/documents/` for the next build. It binds loopback only, caps the body size,
validates every document, and refuses any URI the dataset does not already reference.

Any static host works for deployment. The write-back POST is sent **only** when the app is
served from loopback — posting document text to an arbitrary host would disclose which
talks and manuals you have annotated. Off localhost, use **Export fetched content**:

```sh
python3 tools/unpack_export.py ~/Downloads/scripture-notes-content.json
```

## Tests

```sh
python3 -m unittest discover -s tests
```

No pytest, no network, and no dependency on the conference corpus. Coverage is not
measured in this project.

## How the source data is interpreted

**Annotation URIs.** `/scriptures/<volume>/<book>/<chapter>` identifies a chapter, and a
highlight adds a paragraph suffix — `/scriptures/bofm/alma/27.p4`. Non-scripture
annotations use the *identical* scheme (`/general-conference/2022/10/43gong.p25`); the
only difference is that the `p` number is a paragraph rather than a verse.

**Paragraph ids sit on headings too, and are not all `pN`.** `<h2 id="p36">` is a
legitimate target, and so are `title29`, `aside2_p1`, `figure1_p29`, `study_summary1`, and
the opaque ids (`p_iilzI`) used in talks from 2025 on — 574 of 14,225 highlight entries,
every one carrying a `Pid`. Requiring `pN` left 273 annotations with no anchor at all. An
anchor must start with a letter, so a handbook section number (`/handbook/…/8.1`) is not
mistaken for one.

**Ids are neither contiguous nor monotonic.** One talk carries 56 paragraphs numbered
`1..58` in the order `…18, 59, 19…`, because pull quotes and sidebars are interleaved in
the DOM. Anything that assumes `pN` sits at list position `N-1` is measuring id numbering,
not content — `paragraphs.sort` stores DOM position for this reason.

**Anchoring is doubly redundant.** A paragraph carries both `id="p25"` and
`data-aid="152799681"`, and the annotation stores the latter as `Pid`. `Pid` survives
content revisions while paragraph numbering does not, so anchoring tries `Pid` first and
falls back to the paragraph id.

**Text must be normalised before it is compared.** `html.unescape` → NFC → collapse
whitespace, via `gospel_content.norm_text`. Skipping either of the first two makes
identical text compare unequal — live `D&amp;C` against `D&C`, or precomposed `ü` against
`u` + combining diaeresis — and the mismatch looks exactly like corrupted data.

**Highlight offsets are word offsets, not character offsets.** For scripture they also
count the verse number, which Gospel Library prints as word 1, so a verse-text word index
is `offset - 1`. `-1` means "run to the start / end". The shift was established by scoring
candidate conventions against the 665 fully bounded highlights, counting how often a span
boundary lands on a clause boundary (interior boundaries only):

| convention | clean interior starts | clean interior ends |
|---|---|---|
| offsets read directly | 8.9% | 12.3% |
| **`offset - 1` (used)** | **38.7%** | **62.1%** |
| `-1` start, `-2` end | 38.9% | 21.6% |
| random spans | ~13% | ~19% |

**The equivalent shift for non-scripture paragraphs is not yet decided.** A talk paragraph
has no leading verse number, so the rationale above does not transfer — but a guessed
shift silently tints the wrong words, which is worse than not highlighting at all. Until
`tools/measure_offsets.py` has been run over a filled cache, `DOCUMENT_OFFSET_SHIFT` stays
`None` and document highlights render as whole paragraphs. If the two candidates score
within noise, prefer `0`.

**What gets kept.** An annotation is dropped only if it has no note, no resolvable verse,
**and** no URI — 6 rows out of 9,473 in the 2026-08-02 export, against 3,005 before.
Everything else is retained as `scripture` (5,721), `document` (3,132), or `note` (614).

**Content type comes from the URI, not `CategoryName`.** The URI root classifies every
namespace except `/manual`, which is refined by slug. `CategoryName` is null on 754 rows,
never set on `/handbook/*`, and inconsistent across identical content — the same
Come-Follow-Me slug appears as `Come, Follow Me`, null, *and* `Archived Content` depending
on when the annotation was made — so it is only ever a tiebreaker.

**Tags.** Tag names live only inside the `Content` JSON blob (`Tags` array). The `TagsIds`
column is not a reliable parallel array — 140 rows disagree on length — so names are the
source of truth and ids are ignored.

## Offline archive for conference talks (optional)

If you have a local corpus of conference talks (`conference_talks.db` with
`title, speaker, calling, year, season, url, talk`), `tools/build_alignment.py` can turn it
into an anchored offline archive. The corpus stores plain text with no paragraph ids, so it
cannot resolve an anchor alone; aligning its paragraph *sequence* against fetched content
recovers the mapping, measured at 99.9% over 242 annotated talks.

```sh
# once, with a connection: fetch, align, verify, store the map
python3 tools/build_alignment.py --corpus /path/conference_talks.db \
    --annotations ../resources/annotations/<export>.sqlite --learn

# thereafter, with no network at all
python3 tools/build_alignment.py --corpus /path/conference_talks.db \
    --annotations ../resources/annotations/<export>.sqlite
```

Corpus-derived text is marked `source='archive'` and the reader says so, because a
scrape may predate a revision of the live page.

A document's map is stored only if *every* anchor its annotations need resolved — a
partial map is discarded rather than risk placing a highlight on the wrong paragraph.
`p1`/`p2` are synthesised from the `speaker`/`calling` columns, which is where the scraper
put the byline; note that talks from roughly 2019 on no longer number the byline at all.

The corpus lives outside the repo, so `--corpus` (or `$CONFERENCE_CORPUS`) defaults to
absent and every mode reports "unavailable" rather than failing. Nothing else depends on it.

## Using it

- **Search in — Both / Notes / Content** decides which text a search term is matched
  against. It no longer filters the list; content-type checkboxes do that.
- **Content type** — one checkbox per bucket with live counts. All-checked and
  none-checked both mean "no constraint", so unticking everything can never leave you
  looking at nothing. Volume and Book grey out when Scriptures is unchecked.
- **Search** matches plain text by default; tick **Regex** for a JavaScript regular
  expression, **Aa** for case sensitivity. Those two only shape a search term, so they dim
  until you type one.
- **Tag regex** is a second tag constraint, matched case-insensitively against tag *names*.
  It combines with clicked tags through the same `all`/`any` toggle. Note this differs from
  the box above it, which only narrows which chips are listed.
- **The tag list follows the results.** On **all** the chooser offers only tags found on
  the current results, so no click can land on zero results. On **any** it widens, since an
  unrelated tag would otherwise be unreachable.
- **Click a scripture reference** to open the whole chapter with every highlight in place.
  **Click a talk or manual reference** to open just the paragraphs you annotated —
  downloading them first if needed, with a link to the Church's site whenever that fails.
- **Download in the background** fills the content cache while you are idle and online, so
  it is there offline later. Off by default.
- `/` focuses the search box, `Esc` closes the reader.
