# Code Review Report — non-scripture annotation content

Reviewed using the `reviewer` skill. Scope: the 17 files listed in the brief, against baseline
`2e92ce3` and `requirements.md`. Full test suite run (`73 tests, OK`). No network requests were
made; the real 2026-08-02 export and `scripture_text.db` were present locally, so the retention
and anchoring claims below were verified against real data by running the build.

## Summary

| Severity | Logic | Security | Quality | Performance | Test coverage |
|----------|-------|----------|---------|-------------|----------------|
| Critical | –     | –        | –       | –           | –              |
| High     | 2     | –        | –       | –           | –              |
| Medium   | 6     | 3        | 1       | –           | 1              |
| Low      | 5     | –        | 4       | 2           | –              |

---

## High

### Logic & correctness

- **`webapp/build_data.py:383`** — every annotation with *any* URI is classified `document`,
  rather than R2's rule (`document` = URI with ≥1 paragraph-suffixed highlight **or** a URI
  resolving to a known document). The `kind` counts therefore miss R4's mandated figures by far
  more than the 1% regression threshold.

  Concrete failure scenario: running the real build (`python3 build_data.py --verses
  ../scripture_text.db --annotations ../resources/annotations/scripture_annotations_20260802.sqlite`)
  prints `5721 scripture, 3133 document, 613 note, 6 dropped`. R4 requires `document ≈ 2,999`
  and `note ≈ 753`; the build is **+4.5% on `document` and −18.6% on `note`**, and R4 says
  "a build departing from these by more than 1% must be treated as a regression". The README
  (line ~"Everything else is retained as `scripture` (5,721), `document` (3,133), or `note`
  (613)") records the wrong numbers as if they were correct.

  Implementing R2 literally reproduces the spec exactly — I ran the strict rule over the same
  export and got `scripture 5,721 / document 2,998 / note 754`, matching R4's 5,721 / ~2,999 /
  ~753 to within a row. So ~135 annotations that should be `note` (bucket **My Notes**) are
  filed as `document`. User-visible consequence: they get an "openable" reference button, a
  `documents` row, and a reader that tries to fetch content that does not exist (including the
  literal URI `/journal`), and they disappear from the My Notes content-type facet.

- **`webapp/gospel_content.py:28` (used at `webapp/build_data.py:322`)** — `HIGHLIGHT_URI`
  accepts only `<uri>.p<digits>`, so any other anchor shape is dropped before `Pid` is ever
  consulted, even though every one of those entries carries a usable `Pid`.

  Concrete failure scenario: over the real export, 574 of 14,225 highlight entries have anchor
  suffixes such as `.title1` (191), `.aside1_p3` (27), `.figure1_p29` (23), `.title_number24`,
  `.study_summary1`, `.p_jxeTo` (the base-36 ids used in 2025 conference talks). All 574 carry a
  non-null `Pid`. **204 non-scripture annotations have no parseable anchor at all**, so they get
  zero `highlights` rows; opening one fetches the document successfully and then renders "No
  readable text at this source" with no highlighted text, permanently. Because
  `parse_document_highlights` gates on the URI regex before looking at `Pid`, the Pid-first
  anchoring the change is built around never runs for these rows. (`extract_paragraphs` /
  `parseParagraphs` also hard-require `id="pN"`, so `p_jxeTo` paragraphs would not be extracted
  either.)

---

## Medium

### Security

- **`webapp/dev_server.py:72`** — the dataset allow-list fails open:
  `if self.known_uris and doc["uri"] not in self.known_uris`. An empty allow-list disables the
  check entirely, and `load_known_uris` (lines 94–103) returns an empty frozenset on a missing
  file **and swallows every `sqlite3.Error`**.

  Concrete failure scenario: run `./serve.sh` before ever building (or with an `app.sqlite` from
  before this change, which has no `documents` table). `load_known_uris` returns `frozenset()`,
  and `POST /_cache/<sha256 of any uri>` now writes a file for a URI the dataset never
  referenced — precisely what R34 says must be rejected. The server prints "(0 documents known)"
  but does not refuse to accept writes.

- **`webapp/dev_server.py:47`** — `do_POST` validates the path, size and payload but never the
  request's provenance: no `Origin`/`Host`/`Content-Type`/`Sec-Fetch-Site` check.

  Concrete failure scenario: while `serve.sh` is running, the user visits any web page; that page
  issues `fetch("http://127.0.0.1:8000/_cache/<sha>", {method:"POST", headers:{"Content-Type":
  "text/plain"}, body: attackerJson})`. That is a CORS *simple* request — no preflight — so the
  browser sends it and the handler writes the file; only the response is hidden from the
  attacker. Combined with the fail-open above (no allow-list needed), arbitrary attacker text is
  written into `.cache/documents/` and embedded into the user's dataset by the next build. R52
  calls this endpoint "safe by construction"; a same-site or `Origin` check would make it so.

- **`webapp/gospel_content.py:224` → `webapp/app/app.js:764-767`** — `canonical_url` is accepted
  as any string by `validate_cache_doc`, carried into `documents.canonical_url`, and rendered as
  `<a href="…">` (`escapeHtml` prevents markup injection but not a dangerous scheme).

  Concrete failure scenario: a cache file (planted via the endpoint above, or a hand-edited
  export unpacked with `tools/unpack_export.py`) containing
  `"canonical_url": "javascript:fetch('…'+localStorage.warmContent)"` produces a reader link
  that executes script in the app's origin when the user clicks "Open on churchofjesuschrist.org".
  Values fetched by the app itself are safe (they are prefixed with `CONTENT_ORIGIN + "/study"`);
  only the cache path is unvalidated.

### Logic & correctness

- **`webapp/gospel_content.py:219`** — `"text": norm_text(text) if "<" in text else text.strip()`
  violates R19 ("must live in one shared helper used by every caller"). Text without a `<`
  skips entity decoding, NFC composition and whitespace collapsing.

  Concrete failure scenario (verified):
  `validate_cache_doc({"uri":"/a","paragraphs":[{"para_id":"p1","text":"D&amp;C 121  and  x"}]})`
  returns the text verbatim — `D&amp;C 121  and  x`. The app HTML-escapes on render, so the
  reader displays the literal string `D&amp;C`. The browser's `parseParagraphs` uses
  `textContent`, which decodes entities, so build-embedded and IndexedDB copies of the *same*
  paragraph differ — exactly the cross-source mismatch R19 exists to prevent — and the differing
  whitespace changes `len(text.split())`, i.e. the word count the clamped spans are built on.

- **`webapp/app/app.js:1129-1133`** — the "Select all / Select none" control is a no-op in one of
  its two states; both branches produce an empty `state.categories`:
  `if (categoryActive()) state.categories.clear(); else state.categories = new Set();`

  Concrete failure scenario: with no content-type filter active the button reads "Select none".
  Clicking it clears an already-empty set; `renderCategories` recomputes `on = !categoryActive()`
  → every box redraws checked and the label stays "Select none". The user clicks a button that
  visibly does nothing, twice, and concludes the filter is broken.

- **`webapp/app/app.js:816`** — an annotation whose anchors do not resolve is reported as
  `"No readable text at this source."`, which is the R16/R26 `empty` state, not the required
  "no paragraph content at this reference" for the URI-with-no-usable-anchors case (edge-case
  table, row 1).

  Concrete failure scenario: open any of the 204 annotations from the High finding above, or one
  of the 82 no-highlight documents. The fetch succeeds and returns a full talk; `documentPassages`
  is empty because the annotation has no `highlights` rows, so the reader claims the *source* has
  no readable text. The card, via `contentPendingLabel`, says the right thing — the two paths
  disagree.

- **`webapp/tools/build_alignment.py:191`** —
  `for order, para_id in enumerate(sorted(mapping, key=lambda p: int(p[1:])))` derives `sort`
  from the numeric part of `para_id`, which R14 explicitly forbids, and writes `"pid": None`,
  discarding the primary anchor. It writes into the same `.cache/documents/` as real fetches, so
  it silently **overwrites** a correct cached document with a degraded one.

  Concrete failure scenario: a talk whose live DOM order is `…p18, p59, p19…` (the case the
  codebase documents in three places) is annotated at p18, p19 and p59. `build_alignment.py`
  writes sort 0/1/2 for p18/p19/p59, so the reader shows p59 last instead of second, and the
  build's Pid-first anchoring loses its Pid for that document. Additionally R40 requires
  corpus-served content to be "labelled as served from the local archive"; writing it into the
  ordinary cache means nothing anywhere distinguishes it, so a user cannot tell archive text from
  fetched text.

- **`webapp/app/app.js:902-916, 1213-1216`** — background warming does not implement two of
  R33's three preconditions. There is no metered/`saveData` check anywhere in the file (grep for
  `saveData|connection|metered` returns nothing), and warming starts *immediately* rather than
  after ≥30 s idle: `main()` calls `setWarming(true)` on boot when the pref is stored, and the
  toggle handler calls it directly on `change`.

  Concrete failure scenario: a user on a metered phone connection who left the toggle on opens
  the app; the app begins fetching up to 1,134 documents two at a time from page load, on their
  data plan, with no idle delay. The `idleTimer` scheduled by the same click is a no-op because
  it only fires when `!state.warming`.

- **`webapp/app/app.js:892-897`** — a *transient* warm failure permanently marks the document
  `fetchState = "failed"` for the session, and `warmCandidates` (line 859) then skips it forever.

  Concrete failure scenario: a 500 or a dropped connection while `navigator.onLine` is still true
  (captive portal, flaky wifi) burns two documents per iteration. Their cards switch from
  "Content not downloaded — open to fetch it" to "Content could not be downloaded", and warming
  never retries them; only a page reload clears it. Note also that the "3 consecutive failures"
  rule is evaluated per-result inside a batch, so `[reject, fulfil]` resets the counter to 0 —
  two batches of one failure each never trip the limit.

### Quality & maintainability

- **`webapp/app/app.js:126`** — `paraKey` joins with a literal NUL byte, which makes the file
  binary to git: `git diff 2e92ce3 -- webapp/app/app.js` prints `Bin 26800 -> 45952 bytes` and no
  diff at all. A 500-line change to the app's core file cannot be reviewed, blamed, or merged
  textually. `" "` (an escape, not a raw byte) or `"\x1f"` would keep the same guarantee
  while keeping the file text.

### Test coverage

- **`webapp/tests/test_build_data.py`** — the retention tests cover the cases the implementation
  gets right and none of the boundary the spec actually turns on. There is no test for "URI
  present, no paragraph-suffixed highlight, note present" (the ~135 rows misfiled by the High
  finding — `test_uri_without_note_is_retained_not_dropped` asserts the *no-note* variant), no
  test that a non-`.pN` anchor shape is handled, and no assertion anywhere on the R4 kind counts
  or the R7 category table. Similarly `test_dev_server.py:117` asserts that a missing DB yields
  an empty allow-list but never asserts what the endpoint then *does* with it — the fail-open
  behaviour would pass today's suite unchanged. `test_gospel_content.py` never exercises
  `validate_cache_doc` with entity-bearing tag-free text, which is why the R19 shortcut survives.

---

## Low

### Logic & correctness

- **`webapp/app/app.js:869-871`** — if `navigator.onLine` flips false without the `offline` event
  firing, `warmLoop` returns while `state.warming` stays `true`; the `online` handler
  (line 1194) then refuses to restart because it checks `!state.warming`. Recovery only happens
  via the next user interaction. Cheap fix: set `state.warming = false` before returning.
- **`webapp/app/app.js:192-205`** — `adoptParagraphs` merges IndexedDB paragraphs over
  build-embedded ones rather than replacing the document's set, so a paragraph removed in a newer
  revision keeps its stale build-embedded text while R31 says IndexedDB wins.
- **`webapp/gospel_content.py:85-95` vs R7/R8** — `CATEGORY_HINTS` maps `Youth` → `Other`, and
  there is no `Youth` bucket. R7's table expects "Youth 4" while R8's authoritative bucket list
  has no Youth; worth an explicit decision rather than leaving the two requirements in conflict.
- **`webapp/tools/unpack_export.py:45,56`** — `version > SUPPORTED_VERSION` raises `TypeError`
  on a string version, and `(doc or {}).get(...)` raises `AttributeError` when a list element is
  itself a list, so a slightly malformed export tracebacks instead of reporting a skip.
- **`webapp/tools/build_alignment.py:50`** — `os.path.abspath(path).replace(" ", "%20")` only
  percent-encodes spaces; a corpus path containing `#` or `?` produces a wrong SQLite URI.

### Quality & maintainability

- **`webapp/build_data.py:520`** — `"%d documents (%d with text)" % (counts["documents"],
  len(cache))` reports the number of *cache files*, not the number of built documents that got
  text; with a cache holding documents no longer referenced by the export, the second figure
  exceeds the first.
- **`webapp/build_data.py`** — `documents.fetch_error` is created but never written by any code
  path, and runtime `failed` state is never persisted, so `fetch_state='failed'` (R16) can never
  appear in the database.
- **`webapp/app/app.js:833`** — `refreshCardsFor` is only called from the reader success path, so
  documents fetched by background warming leave every visible card still saying "Content not
  downloaded — open to fetch it" until the next filter change.
- **README / R21** — the offset measurement has not been run, so the required table is absent
  from the README. The fallback (whole-paragraph rendering, `DOCUMENT_OFFSET_SHIFT = None`) is
  spec-compliant and well-tested, so this is a "requirement not yet delivered" rather than a
  defect — flagging it so it is not lost.

### Performance

- **`webapp/app/app.js:853-863`** — `warmCandidates` uses `out.includes(ann.docUri)` inside a
  scan of all 9,473 annotations, i.e. ~1.8 M comparisons, and is called once per warm iteration
  (~570 iterations for a full warm). A `Set` makes it linear. Not fatal at this data size, but
  it runs on the main thread every 500 ms.
- **`webapp/app/service-worker.js:56-80`** — `CONTENT_CACHE` is never versioned or pruned, and is
  explicitly preserved by the `activate` cleanup, so it accumulates a second full copy of every
  API response alongside IndexedDB (~1,100 documents) with no eviction path.
