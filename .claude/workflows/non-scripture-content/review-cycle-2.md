# Code Review Report — non-scripture annotation content (cycle 2)

Reviewed using the reviewer skill.

Scope: the 17 files listed in the brief, judged against
`.claude/workflows/non-scripture-content/requirements.md` (including the
`[amended, cycle 1]` clauses). Baseline `2e92ce3`. No other file under
`.claude/workflows/` was opened. No network request was made to
churchofjesuschrist.org.

Test suite: `python3 -m unittest discover -s tests` → **93 tests, all pass**
(13.9 s). No mojibake found (`grep` for `â€` / `Ã` across the changed files is
clean); every file open in Python code passes `encoding="utf-8"`.

## Summary

| Severity | Logic | Security | Quality | Performance | Test coverage |
|----------|-------|----------|---------|-------------|----------------|
| Critical | –     | –        | –       | –           | –              |
| High     | 2     | –        | –       | –           | –              |
| Medium   | 2     | 2        | 2       | 1           | 1              |
| Low      | 5     | 1        | 5       | –           | 1              |

---

## High

### Logic & correctness

- **`webapp/build_data.py:416-418`** — every paragraph in the cache document is
  written to the `paragraphs` table, not only the ones an annotation references.
  This violates **R15** ("Only paragraphs referenced by at least one annotation
  are stored") and, through it, **R50** (dataset ~18 MB → ~20 MB).
  The cache files themselves contain the whole page, because `app.js`
  `parseParagraphs` (app.js:701-712) extracts *every* `p[id]`/`h1-h6[id]` node and
  `postBack` (app.js:716-725) ships the lot; `build_data.py` then embeds all of it.
  Nothing anywhere narrows the set to referenced anchors — note that
  `tests/test_gospel_content.py:74` even asserts the opposite in a comment
  ("Over-extraction is harmless: only referenced paragraphs are stored").

  Concrete failure scenario: verified by running the real build path. One
  annotation on `/general-conference/2022/10/43gong` anchored at `p1`, with a
  cache document holding 20 paragraphs, produces **20 rows in `paragraphs`**
  instead of 1. Extrapolated across the 3,132 document annotations (≈2,000
  distinct documents × ~40 paragraphs × ~500 bytes) the content tables grow by
  tens of MB rather than the ~1.5 MB the referenced-only rule implies — the
  dataset overshoots the 20 MB budget by more than an order of magnitude, and
  `app.js:235-237` loads all of it into a `Map` on every page load, on a phone.

- **`webapp/app/app.js:546-559` (and `327-338`, `192-213`)** — runtime paragraph
  resolution is by `para_id` only; `pid` is never consulted. **R18** ("A highlight
  resolves to a paragraph by `Pid` (`data-aid`) first, falling back to `para_id`")
  is implemented only in the build (`build_data.py:332`). `state.paragraphs` is
  keyed solely by `paraKey(docUri, paraId)`, and `documentPassages` /
  `refreshContentText` do a single `paraKey` lookup. The `pid` is loaded into
  `state.docHighlights` (app.js:250) and stored on each paragraph record
  (app.js:203-205) — and then never used for anything.

  Concrete failure scenario: this is the *normal* path, because almost every
  document is `unfetched` at build time. Annotation anchors `.../43gong.p9` with
  `Pid: "STABLE"`; the build has no cache, so the highlight row is written as
  `para_id='p9', pid='STABLE'` with no paragraph rows. The user opens the card;
  `fetchDocument` retrieves the current page, where that paragraph has been
  renumbered to `id="p12"` with `data-aid="STABLE"` unchanged. `adoptParagraphs`
  stores it under key `…\x1fp12`; `documentPassages` looks up `…\x1fp9`, misses,
  and the reader reports "1 highlighted paragraph(s) could not be located in the
  current version of this page" — even though the stable anchor is present in
  both the highlight row and the paragraph record. The same miss silently empties
  `ann.contentText`, so the annotation also drops out of "Search in: Content".
  `tests/test_build_data.py::test_pid_wins_over_para_id` covers only the build
  side, so this gap is invisible to the suite.

---

## Medium

### Logic & correctness

- **`webapp/app/app.js:810-818`** — a document that is `cached` but whose anchors
  all miss (and every one of the 82 URI-with-no-highlights `reference` rows) is
  re-fetched over the network on **every** reader open. The early-return requires
  both `isCached(uri)` *and* at least one resolved passage; a bare `reference`
  annotation has `documentPassages(ann).length === 0`, so `.some(p => p.text)` is
  always false and control always falls through to `fetchDocument`.

  Concrete failure scenario: open the same Ensign bookmark ten times → ten full
  content-API requests, each showing "Downloading content…" before settling on
  "No paragraph content at this reference." The edge-case table requires this row
  to render as a metadata-only card with that message and an outbound link; it
  does, but only after a pointless round trip, and it is unusable offline where
  it hits the `!navigator.onLine` branch instead of just rendering.

- **`webapp/app/app.js:918-949`, `951-974`** — two `warmLoop()` instances can run
  concurrently, breaking **R33**'s ≤2-concurrent / ≥500 ms-spacing cap.
  `noteInteraction` sets `state.warming = false` but cannot interrupt a loop
  parked on `await Promise.allSettled(...)`; the 30 s idle timer then calls
  `setWarming(true)`, which sets `state.warming = true` and starts a *second*
  `warmLoop`. When the first loop's fetches finally settle, its `while
  (state.warming)` test now passes and it keeps going.

  Concrete failure scenario: warming is running with two requests in flight over
  a stalled connection (fetch has no timeout here, so a hung request can sit for
  minutes). The user scrolls once at t=0 → `stopWarming`. At t=30 s the idle timer
  fires → second loop starts. At t=45 s the original batch settles → the first
  loop resumes. Four concurrent requests, 250 ms effective spacing, and
  `state.warmFailures` mutated from two loops.

### Security

- **`webapp/dev_server.py:47-66`, `144`** — the write-back endpoint validates
  `Sec-Fetch-Site`/`Origin` but never validates the `Host` header, so it is open
  to DNS rebinding. An attacker page served from `http://evil.example:8000` whose
  DNS is rebound to `127.0.0.1` issues a same-origin `fetch` — the browser sends
  `Sec-Fetch-Site: same-origin` and the check at line 60-63 passes.

  Concrete failure scenario: with `./serve.sh` running, the user visits a hostile
  page. It rebinds and POSTs a well-formed cache document for
  `/general-conference/2022/10/43gong` (a public URI plausibly present in any
  member's annotation set — the allow-list is the only remaining barrier, and its
  contents are guessable). `write_cache` writes the file; the next `build_data.py`
  embeds the attacker's paragraph text, which is then displayed as the user's
  annotated content. No traversal is possible (the filename is a hex hash), so the
  impact is content spoofing rather than arbitrary write — but the fix is one
  `Host` check against `localhost`/`127.0.0.1`.

- **`webapp/app/app.js:716-725`** — `postBack` fires unconditionally against
  whatever origin the app is served from, not only the dev server. **R49** says
  annotation content never leaves the device "except as URI lookups against the
  Church's own API"; when the PWA is deployed to a static host (the documented
  deployment, README "Any static host works"), every document the user opens or
  warms is POSTed in full to that host.

  Concrete failure scenario: the app is hosted on GitHub Pages. Background warming
  is enabled. The host's access logs now record a `POST /_cache/<sha256>` — with a
  body containing the document text — for each of ~2,000 documents, which is a
  complete disclosure of which conference talks, manuals and handbook sections the
  user has annotated, to a third party that is not the Church. It is also pure
  wasted upstream bandwidth on a phone. A `location.hostname === "localhost" ||
  "127.0.0.1"` guard would confine it to the dev affordance R34/R52 describe.

### Quality & maintainability

- **`webapp/build_data.py:52`, `webapp/tools/measure_offsets.py`,
  `webapp/README.md:~113`** — **R21** is not satisfied. The requirement is to
  *measure* shift 0 vs −1 over the 1,275 bounded non-scripture highlights, adopt
  the winner, and record the result and table in the README. What shipped is the
  measuring tool plus the R21 fallback ("Until measured, non-scripture
  partial-paragraph rendering must not ship"): `DOCUMENT_OFFSET_SHIFT = None` and a
  README paragraph saying it has not been decided. The fallback is honoured
  correctly and tested (`test_document_highlights_are_whole_paragraph_until_shift_is_measured`),
  so nothing renders wrongly — but the deliverable is outstanding, and every
  bounded non-scripture highlight currently tints its whole paragraph.
  Failure scenario: the user highlighted six words of a 90-word talk paragraph;
  the reader tints all 90.

- **`webapp/tools/build_alignment.py:216-222`; nothing in `app.js`** — **R40**'s
  "labelled as served from the local archive" is not implemented anywhere. The
  corpus replay writes corpus-derived text into ordinary cache documents, which
  become indistinguishable from fetched content once `build_data.py` embeds them
  (no flag in the cache schema, no column on `documents`, no UI string — `grep`
  for "archive" in `app/` finds nothing). Replay also *overwrites* a genuinely
  fetched cache document for the same URI with a corpus-derived subset.
  Failure scenario: a talk whose live wording was revised is replayed from a 2015
  scrape; the reader shows the old text with the user's highlight on it and
  presents it as the current page's content.

### Performance

- **`webapp/app/app.js:940-946` with `860-868`** — `warmLoop` calls
  `refreshCardsFor(uri)` after every successful warm fetch, and
  `refreshCardsFor` computes an `ids` set, uses it only as an emptiness guard
  (which is never empty for a warm candidate, since candidates are derived from
  annotations), then wipes `el.results.innerHTML` and re-renders **every** card up
  to `state.shown` regardless of whether any of them belongs to that document.

  Concrete failure scenario: the user has clicked "Show more" a few times
  (`state.shown = 400`) and leaves the tab idle with warming on. Each warmed
  document triggers a 400-card teardown and rebuild — ~2 per 500 ms, so ~1,600
  `renderCard` calls per second, sustained for the thousands of documents in the
  queue. Secondarily, wiping and rebuilding the list changes the document height
  and can fire a `scroll` event, which is registered as user interaction
  (app.js:1251-1253) and pauses warming for another 30 s — the feature partially
  defeats itself.

### Test coverage

- **`webapp/tests/test_build_data.py`** — none of the numeric acceptance criteria
  are asserted. **R3** ("exactly 6 of 9,473"), **R4** (`scripture` 5,721 /
  `document` 3,132 / `note` 614, "departing by more than 1% is a regression") and
  **R7** (the 136 null-`CategoryName` rows, per-bucket) have no test and no
  scripted check. The synthetic fixtures exercise each rule in isolation but
  cannot catch a rule interaction that shifts the totals.

  Concrete failure scenario: `webapp/README.md` currently records **3,133
  documents / 613 notes**, while the authoritative amended R4 says **3,132 /
  614** — one row is classified differently from the spec and nothing in the
  suite, the build output, or CI notices. (Both reconcile to 9,473, so the
  discrepancy is a genuine single-row misclassification, most plausibly around the
  `/journal` carve-out at `build_data.py:393`, not a typo in the totals.) Since
  the export is not in the repo, a `--verify-counts` flag on the build or a test
  gated on the export's presence would be the practical form.

---

## Low

### Logic & correctness

- **`webapp/app/app.js:939`** — `state.warmFailures` is incremented by the batch
  size, not by one, so **R33**'s "3 consecutive failures" is really "2 all-failed
  batches / 4 failures" at `WARM_CONCURRENCY = 2`. Scenario: with the API down,
  warming stops after 4 failed downloads rather than 3.
- **`webapp/app/app.js:851-852`** — any reader fetch error (a 500, a timeout)
  marks the document `fetchState = "failed"` in memory, which excludes it from
  `warmCandidates` (app.js:902) for the rest of the session. The edge-case row
  "Network returns mid-fetch to online → `online` event re-enables fetching and
  warming" is only half honoured: warming restarts, but the documents that failed
  during the outage are permanently skipped until reload or a manual **Retry**.
- **`webapp/app/app.js:636-643`** — `contentPendingLabel` returns "Content not
  downloaded — open to fetch it." for a document whose `fetchState` is `cached`
  but whose anchors all missed, which is the opposite of the truth. The `partial
  anchor miss` state has no card-level label.
- **`webapp/build_data.py:393` vs requirements R2/R3** — a row with a `/journal`
  URI and no note title/body is dropped, though R3 says a row is dropped "only
  when it has no note, no resolvable verse, **and** no URI". R2's `note`
  definition requires a note title or body, so such a row satisfies neither kind.
  The two clauses conflict; whichever way it is resolved it moves the "exactly 6"
  figure, so it should be pinned down rather than left implicit.
- **`webapp/build_data.py:419-421`** — the `documents` row is written from
  whichever annotation for that URI is encountered first, including its
  `CategoryName`. Two annotations on one URI with different `CategoryName` values
  (the README itself notes the same slug appears as `Come, Follow Me`, null and
  `Archived Content`) yield `documents.category` disagreeing with one of the
  `annotations.category` values, so the checkbox facet and the reader header can
  label the same document differently.

### Security

- **`webapp/app/app.js:210`, `787`** — there is no client-side equivalent of
  `gospel_content.safe_url`. `canonicalUrl` is written into an `href` and is
  currently safe only because both producers prefix `CONTENT_ORIGIN`
  (app.js:682-683) or passed through `safe_url` in the build. A future import path
  for the export JSON (or a hand-edited IndexedDB record) would put an
  unvalidated scheme straight into the link; `escapeHtml` does not stop
  `javascript:`. Defence in depth only — no current exploit path.

### Quality & maintainability

- **`webapp/app/index.html:56` vs `webapp/app/app.js:1076`** — the HTML ships the
  button label "Select none" while `renderCategories` unconditionally writes
  "Select all". The wrong label is visible until the first render and the two
  sources disagree in the repo.
- **`webapp/app/app.js:1064-1071`** — `renderCategories` rewrites
  `#type-list.innerHTML` on every `applyFilters()`, so toggling a checkbox
  destroys the element that has focus. Keyboard scenario: tab to "Magazines",
  press space, focus lands on `<body>` — the user must tab in from the top again
  for each subsequent box. **R54** ("existing accessibility behaviour must not
  regress") is about existing behaviour, so this is new-UI polish rather than a
  regression, but it is a real cost.
- **`webapp/app/app.js:1119-1135`** — `exportContent` calls
  `URL.revokeObjectURL(url)` synchronously after `a.click()` and never attaches the
  anchor to the document. Both are known to cancel the download in some browsers
  (historically Firefox), and the failure is silent — the status line still says
  "exported N documents".
- **`webapp/dev_server.py:140`** — `known_uris` is snapshotted at process start.
  Rebuilding `app.sqlite` while `serve.sh` is running makes every new document's
  write-back 403, and `postBack` swallows the failure by design (R35), so the
  maintainer gets no signal that the cache stopped filling.
- **`webapp/dev_server.py:73-75`** — the 413 path replies without draining the
  request body. Safe today only because `BaseHTTPRequestHandler.protocol_version`
  defaults to `HTTP/1.0` and the connection is closed; raising it to HTTP/1.1
  would desynchronise the connection.

### Test coverage

- **`webapp/tests/test_alignment.py`** — covers `align` and `corpus_text` only.
  **R39**'s verification gate (`needed.issubset(mapping.keys())`, the whole point
  of the feature — a partial map must be discarded) lives in
  `build_alignment.main()` and is untested, as is the replay path and the "corpus
  absent → unavailable" degradation required by **R41**. `unpack_export.py` has no
  test at all, including the "Export JSON re-imported twice is idempotent"
  edge-case row.

---

## Verified as correct (spot-checked, no finding)

- The `ANCHOR` regex `[A-Za-z][\w-]*` and greedy `HIGHLIGHT_URI` behave correctly
  on `…/8.1` (no match), `…/8.1.p3` → `("…/8.1", "p3")`, `…/32.title29`,
  `p_iilzI`, `aside2_p1`, `figure1_p29`, `study_summary1`.
- `clamp_span` handles `-1`/`None`, out-of-range, reversal and `word_count == 0`
  per R20; the scripture `-1` shift is unchanged.
- R13 (corrupt/hash-mismatched cache file skipped with a warning, build succeeds)
  and R16 (`empty` vs `failed`) are implemented and tested.
- R10 (no network in the build) is asserted by disabling `socket.socket`.
- R34's allow-list fails closed on a missing DB and on an `app.sqlite` without a
  `documents` table, and the path regex rejects traversal, non-hex and short keys.
- R34a: `safe_url` strips non-http(s) schemes from `canonical_url` before it
  reaches the DB.
- R19: `norm_text` is unconditional and the NFC test uses a genuinely decomposed
  literal (U+0308), so it asserts what it claims.
- R32: the service worker's runtime route is scoped to the content origin *and*
  API path; all other cross-origin requests still pass through, and
  `CONTENT_CACHE` is preserved across `activate`.
- R43/R44/R45/R47 and the `/`-focus / `Esc`-close keyboard behaviour are correct;
  volume/book contribute nothing to filtering while disabled.
- Escaping: every interpolation into `innerHTML` in `app.js` passes through
  `escapeHtml`, including error messages, tag names, refs and `err.message`.
