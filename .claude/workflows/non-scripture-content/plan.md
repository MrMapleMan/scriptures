# Plan: non-scripture content — retention, on-demand fetch, and category filters

Investigated against the live export `resources/annotations/scripture_annotations_20260802.sqlite`
(9,473 rows) and the live Gospel Library content API on 2026-08-07. Every number below is
measured, not estimated, except where explicitly marked as a projection.

**Decisions settled with the repo owner** (2026-08-07):
- **Document reader** shows only the paragraphs tied to the annotation. **Scripture reader
  keeps its whole-chapter view** — unchanged from today.
- **No bulk prefetch.** The build populates paragraphs from local cache sources only;
  everything else is lazy-fetched at runtime on first open and written back so later builds
  preload it. See §3.
- Write-back uses **both** a `serve.sh` upload endpoint and an in-app export button.
- The overloaded *Show* control is **split** into a search-target selector + type filters.
- Build **Phases 1–5**.
- Preach My Gospel → **Books & Lessons**. The 618 URI-less journal rows → **My Notes**.
- Classification is **URI-first**, with `CategoryName` as a hint only (evidence in §4).

---

## 0. Why non-scripture is excluded today

Three independent gates in [`webapp/build_data.py`](../../../webapp/build_data.py), all of
which must pass for an annotation to be kept as scripture:

```python
chapter_match = CHAPTER_URI.match(uri)          # ^/scriptures/<vol>/<book>/<chapter>$
is_scripture = bool(chapter_match) and book_url in book_ids

if is_scripture:
    hl, touched, colors = parse_highlights(...)
    if not hl:
        is_scripture = False                     # no highlight resolved to a known verse

if not is_scripture and not has_note:
    counts["dropped"] += 1
    continue                                     # <-- the drop
```

1. **`CHAPTER_URI` only matches `/scriptures/…`.** A talk URI is
   `/general-conference/2022/10/43gong`, so it fails the first regex and is never considered.
2. **The book must exist in `scripture_text.db`** — this also drops JST, Bible Dictionary,
   Guide to the Scriptures, Official Declarations, and the proclamations.
3. **At least one highlight must resolve to a known verse**, else it demotes to `note`.

**The root cause is that retention is coupled to local text availability.** The schema has
nowhere to put an annotation it can't render, so it discards it. Carrying a note is the only
escape hatch, and that is incidental — it works because `note_text` is somewhere to put text.

### What that costs

| CategoryName | kept (scripture) | kept (note) | **dropped** |
|---|---:|---:|---:|
| General Conference | 0 | 41 | **1,337** |
| Church History | 0 | 13 | **313** |
| Magazines/Ensign | 0 | 10 | **290** |
| Books and Lessons | 0 | 23 | **286** |
| Scriptures *(JST/BD/GS/OD, headings)* | 5,721 | 18 | **188** |
| *(null — journal entries)* | 0 | 620 | **134** |
| Come, Follow Me | 0 | 2 | **116** |
| Magazines/Liahona | 0 | 7 | **81** |
| Handbooks and Callings | 0 | 2 | **65** |
| Topics | 0 | 2 | **41** |
| Videos and Images | 0 | 3 | **41** |
| Books and Lessons/Institute | 0 | 1 | **31** |
| Magazines/New Era | 0 | 0 | **28** |
| Music | 0 | 1 | **17** |
| Magazines/YA Weekly | 0 | 0 | **15** |
| Archived Content | 0 | 3 | **8** |
| Friend, Life Help, Seminary, FSY, Youth | 0 | 1 | **14** |
| **TOTAL** | **5,721** | **747** | **3,005** |

**2,999 of the 3,005 dropped rows carry a usable URI.** Only 6 don't.

---

## 1. Findings that make this cheap rather than speculative

**F1 — Non-scripture annotations are structurally identical to scripture ones.**

```
Uri        : /general-conference/2022/10/43gong
Highlights : [{"Uri": "/general-conference/2022/10/43gong.p25", "Pid": "152799681",
               "OffsetStart": -1, "OffsetEnd": -1, "Color": "yellow", ...}]
```

Same `<uri>.p<N>` scheme. The scripture path reads the `p` number as a verse; here it's a
paragraph. `HIGHLIGHT_URI` generalizes by relaxing the `/scriptures/` prefix — the parsing
logic is otherwise unchanged.

**F2 — The export already carries display-quality metadata.** `ItemTitle`="October 2022",
`Location`="Happy and Forever", `SubLocation`="Gerrit W. Gong". **A useful result card needs
zero fetched content.** This decouples retention from fetching, and is the most important
finding here — it's what makes Phase 1 possible with no network dependency at all.

**F3 — The Gospel Library content API is CORS-enabled**, reflecting the request Origin:

```
GET https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content?lang=eng&uri=<uri>
→ HTTP/2 200
  access-control-allow-origin: http://localhost:8000
  access-control-allow-credentials: true
```

Response: `{meta:{title,canonicalUrl,…}, content:{head,body,footnotes}, pids, uri, restricted}`.

**F4 — Paragraph anchoring is doubly redundant.**

```html
<p data-aid="152799681" id="p25">Finally, fifth: As the Golden Rule…</p>
```

`id="p25"` matches the URI suffix **and** `data-aid` matches the highlight's `Pid`. `Pid` is
stable across content revisions; `pN` is not. **Anchor on `Pid` first, fall back to `pN`** —
this makes highlights survive Church content updates, which the scripture path can't do today.

**F5 — It works everywhere.** 10/10 categories fetched (Church History, Books and Lessons,
Ensign, Come Follow Me, General Handbook, Topics, Music, Videos and Images, Liahona, Archived
Content). Random sample of 18 documents: **18/18 succeeded, 0 restricted, 0 failures.**

**F6 — Measured footprint.** 924 documents carry at least one annotated paragraph; 4,174
annotated paragraphs total, mean 4.5 per document. From a 16-document random sample:

| | mean bytes/doc | projected for 924 docs |
|---|---:|---:|
| Full document text | 13,226 | 12.22 MB |
| **Annotated paragraphs only** | **2,138** | **1.98 MB** |

**102 of 102 sampled paragraph anchors resolved — zero misses.** One document in an earlier
sample yielded 0 paragraphs (a video/image page with no `<p id="pN">`); that case is real and
must be handled as `empty`, not as an error.

**F8 — Coverage of what needs fetching.** 924 documents need paragraphs:

| Root | Docs | Local source available? |
|---|---:|---|
| `/general-conference` | 429 | 428 have text locally, but **no anchors** (F9) |
| `/manual` | 285 | no |
| `/ensign` | 93 | no |
| `/history` | 58 | no |
| `/liahona` | 26 | no |
| `/broadcasts`, `/new-era` | 26 | no |
| `/handbook`, `/church-historians-press`, `/ya-weekly`, `/friend`, `/ftsoy` | 7 | no |

Fetchability sampled across every non-GC root: **29/31 documents fetched, 135/135 annotated
paragraphs resolved.** `/manual` — the owner's specific concern — was 4/4 and 14/14. The API
is one uniform endpoint; there is **no per-type path-discovery problem**. The only failures
were `/handbook/handbook-2-administering-the-church` (**HTTP 404** — Handbook 2 was retired
in 2020): 2 documents, 18 annotations, permanently unavailable.

**Realistic ceiling: ~2 of 924 documents cannot be fetched.**

**F9 — The local conference corpus cannot anchor highlights.**
`/mnt/c/Users/henri/Documents (Not Synced)/Programming/python/conference_talks/conference_talks.db`
(89 MB) holds **4,378 talks, 1971–2026, all URLs distinct**, plus a 2,121,622-row
`talk_words` frequency table. `/mnt/c/Users/henri/Downloads/conference_talks.{json,csv}` is
an older export of the same scrape (4,297 talks) — **the `.db` is the better source** and is
what the findings below were measured against.

Coverage is near-total: **428 of the 429 annotated GC documents are present.** The one
absent, `/general-conference/2020/04/saturday-evening-session`, is a session index page
rather than a talk.

Its columns are `title, speaker, calling, year, season, url, talk, footnotes, conference`.
Verified directly: `talk` and `footnotes` contain **0 HTML tags, 0 `data-aid`, and 0 `pN`
markers** — the text is fully stripped. Paragraphs are cleanly `\n\n`-delimited (splitting on
single newlines and on blank lines give identical counts). Annotations address paragraphs
*only* by ids the DB doesn't carry, so the mapping must be recovered by text alignment.

> **Correction.** An earlier version of this finding claimed a ~41% silent mis-anchoring rate
> and rejected the DB outright. That was an artifact of the measurement, not a property of the
> data: it assumed `pN` sits at list position `N-1`. **The live site's ids are non-contiguous
> and non-monotonic** — one talk carries 56 paragraphs numbered `1..58` in the order
> `…18, 59, 19…`, because pull-quotes and sidebars are interleaved in the DOM. Comparing
> `pN-1` against list index therefore measured id numbering, not content.

Aligning the two paragraph **sequences** with `difflib` and then mapping each real id to its
DB index, over a 25-talk sample of documents the owner has actually annotated:

| measurement pass | anchors resolved | mean similarity |
|---|---:|---:|
| sequence alignment, naive text compare | 107/119 — 89.9% | 0.938 |
| **+ `html.unescape()` + NFC normalization** | **116/119 — 97.5%** | **0.979** |
| **+ byline synthesis (below)** | **119/119 — 100%** | — |

**Verified at scale.** A stratified 242-talk sample (60% of the remaining pool: 10 oldest,
10 newest, every talk from 2016 on, remainder spread evenly across 1971–2024; zero fetch
failures) resolved **1,048 of 1,049 anchors — 99.90%**, mean similarity 0.9795, 241 of 242
documents complete, none empty. No era-dependent degradation: every decade from the 1970s
through the 2010s resolved 100%. 282 anchors came from byline synthesis. Combined with the
first pass, **267 of 428 annotated talks (62%) are verified at 99.91%**. Full report in
[`alignment-verification.md`](alignment-verification.md).

The single failure is an annotation on a **section heading**
(`<h2 data-aid="146039650" id="p36">`), which the scraper omits from `talk` — permanent for
this corpus, and resolvable from fetched content via Pid-first anchoring (F4). Note that
`pN` ids are carried by `<h1>`–`<h6>` as well as `<p>`, so **any extraction regex must match
headings too**; matching only `<p>` silently drops them.

The 12 anchors that failed the first pass were **not** content mismatches. Two were artifacts
of the comparison itself:

- **Undecoded HTML entities** — live `D&amp;C 115:4` vs DB `D&C 115:4` (similarity 0.997).
  All 1985 Oaks failures.
- **Unicode composition** — live `ü` U+00FC vs DB `u`+U+0308 combining diaeresis
  (similarity 0.996). All *Our Path of Duty* failures.

The remaining 3 were all `p1` — the byline (`By Elder David A. Bednar`). It is absent from
`talk` because the scraper moved it into `speaker`, and `p2` (the calling) into `calling`.
Those columns reproduce the paragraphs **exactly**, so synthesizing `p1`/`p2` from them closes
the gap. Note this applies to **older talks only**: from roughly 2019 on the site stopped
numbering bylines, and `p1` is body text (verified on 2020 `37nelson` and 2022 `43gong`).

Worked examples in [`alignment-spot-check.md`](alignment-spot-check.md).

**Crucially, this method knows when it fails.** `difflib` reports which paragraphs matched, so
an unresolved anchor is *detected*, not silently mis-rendered — the failure mode that made the
original conclusion disqualifying does not exist under sequence alignment.

**But it still does not avoid fetching.** Computing the alignment requires the live paragraph
text, and once fetched, that text is what gets stored — the DB adds nothing to the build. So
the API remains the paragraph source (§2), for a much narrower reason than first stated: not
unreliability, but circularity.

Where the DB *does* earn its place is §6: full-text search across all 4,378 talks, and
durable offline fallback text for the 428 annotated GC documents — now with **verified
anchors** rather than unanchored text, which is a materially better fallback than first
planned.

**Normalization requirements this establishes.** Any text comparison between sources must
`html.unescape()`, apply `unicodedata.normalize('NFC', …)`, and collapse whitespace before
comparing. This applies to the scripture path too and belongs in the shared helper, not in
one caller — the two bugs above cost 12 of 119 anchors and looked exactly like data
corruption.

**F7 — The offset convention probably does NOT carry over, and this is unresolved.**
Requirement #7 of the spec: scripture word offsets need a `-1` shift because Gospel Library
prints the verse number as word 1. **A talk paragraph has no leading number, so the shift
likely should not apply.** Affected: **1,275 bounded non-scripture highlights**; the other
3,499 are whole-paragraph (`-1`/`-1`) and are unaffected. Decided by measurement in Phase 2,
not intuition.

---

## 2. Feature A — a local content store

### Schema (additive; nothing existing changes shape)

```sql
CREATE TABLE documents (
    uri           TEXT PRIMARY KEY,   -- '/general-conference/2022/10/43gong'
    category      TEXT NOT NULL,      -- normalized bucket (§4)
    raw_category  TEXT,               -- CategoryName verbatim, for provenance
    title         TEXT,               -- Location:    'Happy and Forever'
    subtitle      TEXT,               -- SubLocation: 'Gerrit W. Gong'
    item_title    TEXT,               -- ItemTitle:   'October 2022'
    canonical_url TEXT,               -- from API meta, for the outbound link
    fetch_state   TEXT NOT NULL,      -- 'cached' | 'empty' | 'failed' | 'unfetched'
    fetch_error   TEXT,
    fetched_at    TEXT
);

-- Only paragraphs referenced by an annotation are stored (~4,174 rows, ~2 MB).
CREATE TABLE paragraphs (
    doc_uri  TEXT NOT NULL REFERENCES documents(uri),
    para_id  TEXT NOT NULL,           -- 'p25'
    pid      TEXT,                    -- data-aid, the stable anchor
    sort     INTEGER NOT NULL,        -- document order, for multi-paragraph annotations
    text     TEXT NOT NULL
);
CREATE UNIQUE INDEX paragraphs_ref ON paragraphs(doc_uri, para_id);
CREATE INDEX paragraphs_pid ON paragraphs(doc_uri, pid);
```

`highlights` gains `doc_uri`, `para_id`, `pid` as a parallel addressing mode alongside
`(book_id, chapter, verse)`. `annotations` gains `doc_uri` and a widened `kind`.

### `kind` widens from 2 values to 3

| kind | meaning | count |
|---|---|---:|
| `scripture` | resolves to bundled verse text | 5,721 |
| `document` | **new** — resolves to a non-scripture document | ~2,999 |
| `note` | no resolvable source; note/journal only | ~753 |

New drop rule: **drop only if there is no note, no resolvable verse, *and* no URI** — 6 rows
out of 9,473, down from 3,005.

### Sourcing paragraphs — cache-first, never bulk-fetch

**The build never fetches from the network.** It reads a local content cache
(`webapp/.cache/documents/<sha>.json`, gitignored) and embeds whatever it finds. Documents
absent from the cache are written with `fetch_state='unfetched'`; the annotation is kept
regardless.

The cache is **cumulative**: the app fetches misses at runtime and writes them back (§3), so
each build embeds everything visited since the last one. Initially the cache is empty, so the
first build ships ~18 MB and grows toward ~20 MB as documents are visited.

- Failures never lose data — a document that can't be sourced still has its metadata row and
  its annotations.
- 0-paragraph documents record `fetch_state='empty'`, not `'failed'`.
- `/handbook/handbook-2-administering-the-church` (F8) will permanently sit at `'failed'`
  with an HTTP 404. Expected, not a bug.

Because of F9, the conference DB is **not** a cache source for paragraphs.

---

## 3. Feature B — reader, on-demand fetch, graceful degradation

### The card always renders

Per F2, a `document` card is built from metadata alone:

> **Happy and Forever** · Gerrit W. Gong · October 2022 · General Conference

Highlighted paragraph text layers in when cached. When not cached, the card shows the
reference and a quiet "content not downloaded" affordance. **The card never fails and the
annotation is never hidden** — the core of the ask.

### Reader scope

For `kind='document'`, the reader shows **only the paragraphs tied to that annotation**, in
document order, with highlights in place — not the surrounding document.

`kind='scripture'` **keeps its current whole-chapter reader**
([app.js:468](../../../webapp/app/app.js#L468)) — confirmed by the owner, unchanged from
today. The two readers deliberately differ: scripture has its full chapter bundled locally,
a document does not.

Because the lazy-fetch machinery exists anyway, an optional **"Open full document"** action
could later fetch and show surrounding context on demand. **Not in scope** — noted only so
the fetch layer isn't designed in a way that precludes it.

### Reader states

| State | Behavior |
|---|---|
| **cached** | Render the annotated paragraphs with highlights. |
| **not cached, online** | Metadata header immediately + loading indicator; fetch; render; cache. |
| **fetch fails** (network, 4xx/5xx, CORS change, bot-block) | Header stays. Inline panel: what failed, **Retry**, and **"Open on churchofjesuschrist.org"** via `canonical_url`. |
| **offline, not cached** | Skip the attempt; "not available offline" + outbound link. Detect via `navigator.onLine`; re-enable on the `online` event. |
| **`restricted: true`** | Unavailable-by-policy message, not a retry loop. |
| **empty (0 paragraphs)** | "No readable text at this source" + outbound link. Not presented as an error. |
| **paragraph anchor missing** | Render what resolved; note the rest is unavailable. (0/102 in sampling, but content does get revised.) |

### Runtime caching and write-back

Fetched documents persist in **IndexedDB** (structured paragraph rows, queryable) rather than
raw Cache Storage, so the app can render them exactly as it renders build-embedded paragraphs.
The service worker must **not** add `churchofjesuschrist.org` to the precache list; it gets a
runtime, network-first route scoped to that exact origin and path prefix. All other
cross-origin traffic keeps passing through untouched (spec #46). A single in-flight request
map prevents duplicate concurrent fetches.

**Write-back — both mechanisms, per the owner's decision.** A browser cannot write into
`webapp/.cache/`, so the loop needs an explicit bridge:

1. **`serve.sh` upload endpoint.** Replace `python3 -m http.server` with a small
   `http.server` subclass that also accepts `POST /_cache/<sha>` and writes the JSON into
   `webapp/.cache/documents/`. The app posts each newly fetched document in the background.
   Automatic while serving locally.
   - **Bind to `127.0.0.1` only**, accept only the documented path, cap the body size, and
     validate that the payload's `uri` matches a document the dataset actually references —
     it writes to disk from an HTTP request, so it must not become an arbitrary file-write.
   - This is a *development-time* server. Static deployments keep serving `app/` as-is and
     silently skip the POST (fire-and-forget, failure ignored).
2. **In-app export button.** Downloads a single JSON of everything in IndexedDB, to be
   dropped into `webapp/.cache/documents/`. Covers the case where the app runs somewhere
   other than `serve.sh` — a phone, a static host — which is exactly where most browsing
   happens.

**Recommended addition: idle background warming.** When online and idle, fetch unvisited
documents a few at a time (respecting the concurrency and delay limits) until the cache is
complete, posting each back. This satisfies the owner's stated goal — a cache that fills so
it can be preloaded next time — without requiring 924 manual clicks, and without a bulk
prefetch at build time. Off by default behind a visible toggle.

### Risk, stated plainly

**This introduces a runtime dependency on an undocumented third-party API.** It works today
and is CORS-enabled today. It could change shape, require auth, or start bot-blocking — the
site already sets Akamai `_abck`/`bm_sz` cookies on its HTML routes.

Because the owner chose cache-first over bulk prefetch, that dependency is on the critical
path for any document not yet visited. Three mitigations:

- **Phase 1 needs no API at all** — every annotation is retained, searchable, and carries a
  readable card from export metadata alone.
- **Every failure path ends at a working link** to churchofjesuschrist.org.
- **The cache is durable.** Once written back, a document survives the API changing forever.
  This is the strongest argument for the idle background warming below: it converts a
  standing dependency into a one-time one.

**The app must never require the API to be useful.**

---

## 4. Feature C — content-type filters

### Classify by URI, not by CategoryName

Cross-tab of URI root against `CategoryName` across all 9,473 rows:

```
/scriptures          (5928)  Scriptures=5927, (null)=1
/general-conference  (1378)  General Conference=1378
/manual              ( 771)  Books and Lessons=307, Come Follow Me=118, (null)=116,
                             Handbooks=67, Church History=51, Topics=43
/(no uri)            ( 619)  (null)=618, Books and Lessons=1
/ensign              ( 300)  Magazines/Ensign=300
/history             ( 273)  Church History=273
/liahona             (  88)  Magazines/Liahona=88
/broadcasts          (  45)  Videos and Images=44, Books and Lessons=1
/new-era             (  28)  Magazines/New Era=28
/handbook            (  18)  (null)=18          <-- never categorized
/ya-weekly           (  15)  Magazines/YA Weekly=15
```

**The URI root is a perfect classifier for every namespace except `/manual`.** Meanwhile
`CategoryName` is demonstrably unreliable: null on 754 rows, never set on `/handbook/*`, and
inconsistent on identical content — the same Come-Follow-Me slug pattern appears as
`Come, Follow Me`, `(null)`, **and** `Archived Content` depending on when the annotation was
made.

**Rule: URI root → bucket; `/manual` refined by slug pattern; `CategoryName` used only as a
tiebreaker for slugs no pattern covers.** Store `raw_category` for provenance so an unknown
future category degrades into **Other** rather than vanishing.

### Recovering the 754 null-category rows

**618 have no URI** and are `Type=journal` → **My Notes**.
**136 have a URI** and classify cleanly:

| URI slug | Rows | → bucket | evidence |
|---|---:|---|---|
| `come-follow-me-*` (4 variants) | 54 | Come, Follow Me | identical slugs categorized so elsewhere |
| `preach-my-gospel-a-guide-to-missionary-service` | 43 | **Books & Lessons** | owner's decision |
| `/handbook/handbook-2-administering-the-church` | 18 | Handbooks & Callings | matches `general-handbook` |
| `my-calling-as-a-counselor-in-the-elders-quorum-presidency` | 5 | Handbooks & Callings | |
| `for-the-strength-of-youth` | 4 | Youth | a sibling row is already tagged Youth |
| `true-to-the-faith` | 3 | Books & Lessons | |
| `hear-him-launch` | 3 | Other | unclear — see open items |
| `family-home-evening-resource-book` | 2 | Books & Lessons | |
| `family-guidebook` | 1 | Books & Lessons | |
| `leadership-instruction-april-2024` | 1 | Handbooks & Callings | |
| `/journal` | 1 | My Notes | |
| `/scriptures/bofm` | 1 | Scriptures | |

135 of 136 recovered; `hear-him-launch` (3 rows) lands in **Other** pending a call.

### The checkboxes

| Checkbox | Sources | Count |
|---|---|---:|
| Scriptures | `/scriptures/*` | 5,928 |
| General Conference | `/general-conference/*` | 1,378 |
| My Notes | no URI, `/journal` | 619 |
| Magazines | `/ensign`, `/liahona`, `/new-era`, `/ya-weekly`, `/friend`, `/ftsoy` | 438 |
| Books & Lessons | `/manual/*` study manuals + Preach My Gospel + Institute/Seminary | ~390 |
| Church History | `/history/*`, `/church-historians-press/*`, `gospel-topics-essays`, `revelations-in-context`, `first-vision-accounts` | 326 |
| Come, Follow Me | `/manual/come-follow-me-*` | ~172 |
| Handbooks & Callings | `/handbook/*`, `general-handbook`, calling materials | ~90 |
| Videos & Images | `/broadcasts/*` | 45 |
| Topics | `/manual/gospel-topics` | 43 |
| Music | `hymns`, `childrens-songbook` | 18 |
| Other | anything unmatched | ~10 |

Derive the list from the data at load time with counts — **never hardcode it in HTML**.

### Behavior

- Default **all checked**. All-checked and none-checked both mean "no constraint" — never show
  an empty app because every box got unticked.
- Counts reflect the *other* active filters, mirroring the tag facets (spec #32).
- Counts toward the filter badge (spec #29) only when not all are checked.
- **Volume** and **Book** selects are scripture-only: disable them when Scriptures is
  unchecked rather than leaving dead controls.

### The Show control is split (decided)

The current **Show — All / Notes / Scripture** does two jobs at once (spec #26). It becomes:

- **Search in:** `Notes` / `Content` / `Both` — purely a search-target selector.
  ("Verse text" → "content text", since content is no longer only verses.)
- **Content type:** the new checkboxes — purely a filter.

---

## 5. Sequencing

Each phase is independently shippable and leaves the app working.

**Phase 1 — Retain everything.** Widen `kind`, add `documents`/`paragraphs`, relax
`HIGHLIGHT_URI`, rewrite the drop rule, populate documents from export metadata only — **no
network**. Result: 9,467 of 9,473 annotations searchable by title/author/tags/notes. Cards
render; the reader offers the outbound link. *Most of the value, zero API dependency.*

**Phase 2 — Decide the offset convention (F7).** Port the clause-boundary scoring harness that
produced the README's 38.7%/62.1% table; run it over the 1,275 bounded non-scripture
highlights, scoring shift=0 against shift=−1. Publish the table in the README beside the
scripture one. **Blocks Phase 3's partial-paragraph rendering only.**

**Phase 3 — Cache-first paragraph embedding.** `build_data.py` reads `webapp/.cache/documents/`
and embeds any paragraphs it finds; anything absent stays `fetch_state='unfetched'`. No
network in the build. Reader renders cached paragraphs with highlights. Grows toward ~2 MB as
the cache fills.

**Phase 4 — Runtime fetch + degradation.** All reader states from §3, the runtime
service-worker route, offline detection, retry, outbound links.

**Phase 5 — Category filter UI.** Checkboxes, faceted counts, the Show-control split, and
disabling Volume/Book when Scriptures is off.

**Phase 6 (follow-on) — Cache-version safety.** Open question #2 of the requirements doc
becomes load-bearing once data changes more often: have `build_data.py` emit a dataset hash
into `meta` and have the app compare it, replacing the hand-edited `CACHE` constant.

### Tests

The project has none. These features add pure, fixture-shaped functions that are the right
place to start:

- URI classification across all observed roots and `/manual` slug patterns, including the 136
  recovered rows, the 6 URI-less non-journal rows, and an unknown slug falling to **Other**
- The retention decision table (`scripture` / `document` / `note` / drop)
- Offset → word-range mapping under both conventions, with clamp and swap cases
- `Pid`-first anchoring with `pN` fallback, including a Pid-not-found case
- Fetch-failure handling: timeout, 404, malformed JSON, `restricted`, 0-paragraph

Network is mocked throughout; **no test may hit the live API.**

---

## 6. The conference corpus — two features it *can* support

Per F9 the DB can't *independently* resolve `pN` anchors, but once an alignment has been
computed against fetched content it reaches 99.9%. Neither feature below is blocked by that:

- **Anchored offline fallback for General Conference.** Store the alignment (a `pN → DB index`
  map, a few KB per talk) alongside the cache. When a GC document isn't cached and the API is
  unreachable, render the talk from the local corpus **with highlights in the right place**.
  Covers 428 of 924 documents — the largest single category — and is a materially better
  fallback than the unanchored text originally planned.
- **Full-text search across all 4,378 conference talks**, not just the 429 annotated ones. The
  app currently can't search anything you haven't annotated. Larger feature: the corpus is
  89 MB, so it needs its own dataset and probably FTS5 rather than the in-memory linear scan
  of spec #55. **Out of scope for Phases 1–5** — recorded so it isn't lost.

Both are optional and neither blocks the main plan.

## 7. Open items

1. **`hear-him-launch` (3 rows)** — no category anywhere in the export. Parked in **Other**.
2. **The 82 documents referenced only by `reference`-type annotations** (1,006 distinct URIs
   vs 924 with an annotated paragraph) have no paragraph to show. They render as
   metadata-only cards; confirm that's acceptable rather than fetching a lead paragraph.
3. **Idle background warming** (§3) — recommended but not yet approved.
4. **Unanchored offline fallback** (§6) — recommended but not yet approved.
