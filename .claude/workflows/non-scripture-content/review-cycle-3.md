# Code Review Report — cycle 3 (non-scripture annotation content)

Reviewed using the `reviewer` skill.

Scope: the 18 files listed for review, judged against
`.claude/workflows/non-scripture-content/requirements.md` (the only file read from that
directory). Baseline `2e92ce3`. Test suite run: `python3 -m unittest discover -s tests` →
**105 tests, OK, 15.4s**, including `test_real_export` (the real export and
`scripture_text.db` are both present, so those 8 acceptance tests genuinely ran rather
than skipping). No network requests were made to churchofjesuschrist.org.

## Verification performed beyond reading

- Re-ran a full build against the real 2026-08-02 export with an empty cache:
  `scripture 5721, document 3132, note 614, dropped 6` — **exactly** R3/R4, reconciling to
  9,473.
- Reconciled every highlight entry: 14,225 entries in the export → 14,063 highlight rows
  written + 162 entries whose `Uri` is `null` (metadata-only annotations, per the edge-case
  table). **0 entries with a base URI differing from the annotation's `Uri`** (so the
  `match.group(1) != doc_uri` guard in `parse_document_highlights` discards nothing today),
  and exactly **1** entry whose anchor fails the regex (see L6). No silent loss.
- Independently recomputed the R7 null-`CategoryName` table (see M4 — it does not match).
- Scanned every changed file for mojibake (`â€`, `Ã`) — **clean**. All file I/O in the new
  Python specifies `encoding="utf-8"`.

## Summary

| Severity | Logic | Security | Quality | Performance | Test coverage |
|----------|-------|----------|---------|-------------|---------------|
| Critical | 0 | 0 | 0 | 0 | 0 |
| High     | 0 | 0 | 0 | 0 | 0 |
| Medium   | 4 | 0 | 0 | 0 | 2 |
| Low      | 3 | 0 | 6 | 1 | 0 |

No security findings. `dev_server.py` — the file that writes disk from an HTTP body — is
the strongest part of the change; I tried to break it and could not (details at the end).

---

## Medium

### Logic & correctness

- **`webapp/app/app.js:872`** — the reader's `restricted` branch is **unreachable in
  practice**, so a restricted document renders an empty reader body on every open after the
  first. `doc.restricted` is only ever set by `adoptParagraphs` (line 216) from an
  IndexedDB document, and a restricted API response carries zero paragraphs, so
  `fetchState` becomes `"empty"` (line 213) and `isCached()` (line 773) returns true —
  which returns at line 868–871, before the restricted check at 872. Violates R26 /
  edge-case row "API returns `restricted: true` → distinct message".
  Concrete failure scenario: open a restricted document once online → the post-fetch branch
  at line 888 correctly shows "This content is not available…". Reload the page (IndexedDB
  is re-adopted) and open the same annotation → `isCached` short-circuits →
  `renderDocumentBody(ann)` with no notice → the panel shows only the byline and the
  outbound link, with no explanation of why there is no text.

- **`webapp/app/app.js:848-851`, reached from `:868`** — the `empty` and *total*
  anchor-miss reader states render **no explanatory text at all**. The "could not be
  located" notice is gated on `passages.length !== missing.length`, so it fires only for a
  *partial* miss. R26 requires both `empty` and the anchor-miss state to be surfaced.
  Concrete failure scenario: `/broadcasts/article/<video-only-page>` is fetched, yields 0
  paragraphs → `fetch_state='empty'`. Click its reference → `isCached()` is true ('empty' is
  in the list) → `renderDocumentBody(ann)` with no notice → every passage has `text === null`
  → `missing.length === passages.length` → the notice is suppressed → the reader is blank
  below the link. The *card* for the same annotation correctly says "No readable text at
  this source." via `contentPendingLabel` (line 667), so the two views disagree.

- **`webapp/build_data.py:84-96` (schema) and `:434-443`** — `restricted` is validated and
  preserved by `validate_cache_doc` (`gospel_content.py:257`) but the `documents` table has
  no `restricted` column and `build_annotations` never reads it, so the restricted state
  cannot survive a rebuild. Combined with the previous finding, a restricted document is
  correctly labelled exactly once, at first fetch, and never again.
  Concrete failure scenario: fetch a restricted doc → write-back → rebuild → open the app in
  a browser with no IndexedDB copy (or after clearing site data) → the document reports
  `fetch_state='empty'` with `restricted` lost, and the reader shows a blank body.

- **`webapp/gospel_content.py:174`** — an unrecognised `/manual` slug falls through to
  `"Books & Lessons"`, not `"Other"`. R6 requires an unrecognised slug to classify as
  **Other**, and R7's table puts `/manual/hear-him-launch` (3 rows) in **Other** (Open
  question 1 says it is "parked in Other"). Verified against the
  real export: the 136 null-`CategoryName` URI rows come out as
  `Books & Lessons 56, Come Follow Me 54, Handbooks & Callings 24, My Notes 1, Scriptures 1`
  — i.e. **Other = 0**, where R7 requires Other = 3.
  A second, related deviation: `/manual/for-the-strength-of-youth` splits across two buckets
  — the 4 rows with a null `CategoryName` land in Books & Lessons (correct per the cycle-1
  amendment) while the 1 row carrying `CategoryName='Youth'` falls to **Other** via
  `CATEGORY_HINTS`. R7 as amended states `/manual/for-the-strength-of-youth` **is** Books &
  Lessons, and R5 says the URI decides; here `CategoryName` overrides it for one row.
  Concrete failure scenario: tick "Books & Lessons" in the content-type filter and the 3
  `hear-him-launch` annotations appear there instead of under Other; tick "Other" and the
  single FTSOY row appears alongside them while its 4 siblings do not. Nothing is lost — the
  impact is 4 misfiled rows out of 9,473 and a silently-resolved open question.

### Test coverage

- **`webapp/tests/`** — there is **no test of any kind for `app/app.js`**, which is where
  roughly half the new logic now lives: Pid-first runtime anchoring, the seven reader
  states, IndexedDB-wins adoption, the in-flight map, the warming loop, and the
  content-type filter semantics (R43/R44/R45/R47). The three reader-state findings above
  are precisely what a runtime test would have caught. This is partly structural — R51
  forbids a build toolchain and the project has no JS harness — but it should be stated
  plainly rather than left implicit: the Python side is well covered and the browser side is
  covered by nothing.

- **`webapp/tests/test_real_export.py:80-84`** — `test_r7_journal_rows_are_notes_not_documents`
  is the only test touching R7, and it asserts only `categories["My Notes"] > 600`. R7 gives
  a precise per-bucket table for the 136 null-`CategoryName` rows and none of it is asserted,
  which is why M4 above went unnoticed through two prior cycles. An assertion of the form
  "classify() over the null-category rows yields {Come Follow Me: 54, …, Other: 3}" would
  have failed.

---

## Low

### Logic & correctness

- **`webapp/tools/build_alignment.py:167-195, 216-225`** — in `--learn` mode the tool
  fetches the live page (line 169), extracts its real paragraphs (line 175), and then throws
  that text away, writing corpus-derived text with `source: "archive"` instead. Because
  `write_cache` overwrites by URI hash, this can also *downgrade* a cache document the app
  previously wrote from a live fetch. Failure scenario: browse a talk in the app (cache doc,
  `source='fetched'`, live wording), then run `build_alignment.py --learn`; the cache entry
  is replaced with archive text and the reader thereafter says "the wording may be out of
  date" about text that was live a minute earlier.

- **`webapp/gospel_content.py:229`** — `re.match(r"^%s$" % ANCHOR, pid_name)`: Python's `$`
  also matches before a trailing newline, so `"p1\n"` passes validation and is stored as a
  `para_id`. Harmless today (`write_cache` names files from `sha256(uri)`, never from
  `para_id`, so there is no traversal), but it means a `para_id` that can never match a real
  DOM id is accepted into the dataset. `re.fullmatch` would close it. Related: `sort` accepts
  `True` (bool is an int subclass, becomes 1) and negative integers.

- **`webapp/tools/measure_offsets.py:54`** — samples are collected by matching `para_id`
  only, with no Pid-first fallback, contradicting R18 and the rest of the codebase. Failure
  scenario: on any page that was renumbered between annotation and fetch, the paragraph is
  present in the cache under a new `para_id` but is skipped, so R21's measurement silently
  runs on a smaller and non-random subset — the exact sample bias that would make the
  measurement inconclusive.

### Quality & maintainability

- **`webapp/build_data.py` (whole file)** — R19 says the normalisation helper must be used
  by *every* caller "including the scripture path", and "Out of scope" reinforces that the
  scripture path changes only for R19. It does not: `parse_verse_highlights` uses
  `verse_text.get(...)` raw and `len(text.split())` for the word count, and `build_data`
  never imports `norm_text`. I verified this is currently **inert** — across all 41,995 rows
  of `scripture_text.db` there are 0 HTML entities, 0 non-NFC strings, 0 NBSPs and 0
  whitespace anomalies — so nothing observable changes. It becomes live the day the verse DB
  is regenerated from a different source.

- **`webapp/app/app.js:1338-1340` / `:984-988` / `:1026`** — the warming toggle's persisted
  preference and its checkbox can disagree. When warming self-pauses on 3 consecutive
  failures (or on completion) it sets `el.warmToggle.checked = false` directly, which fires
  no `change` event, so `localStorage.warmContent` stays `"1"` and warming re-arms on the
  next page load. R33 wants the toggle state to persist; here the *displayed* state and the
  *stored* state diverge after an auto-pause.

- **`webapp/app/app.js:21` vs `:939`** — `WARM_MAX_FAILURES = 3` (consecutive all-failed
  batches) and `WARM_MAX_ATTEMPTS = 3` (per-document attempts) are near-identical names with
  the same value and different meanings, declared 900 lines apart. Easy to conflate when
  changing either.

- **`webapp/app/app.js:125`** — the comment says "NUL-joined"; the separator is `\x1f`
  (US), not NUL. The reasoning is right, the name is wrong.

- **`webapp/dev_server.py:128-134`** — `load_known_uris` leaks the sqlite connection when
  `con.execute` raises (the `except sqlite3.Error` path returns without `con.close()`).
  Startup-only, one connection, so purely cosmetic. Separately: the allow-list is a
  **startup snapshot**, so rebuilding while `serve.sh` is running makes every newly-added URI
   403 until the server is restarted, with no message explaining why — worth a line in the
  README.

- **`webapp/build_data.py:452`** — `documents.category` / `raw_category` / `title` /
  `subtitle` are taken from whichever annotation for that URI happens to be seen first
  (`seen_docs` guard at line 433). For unmatched `/manual` slugs with inconsistent
  `CategoryName` (e.g. FTSOY), `documents.category` can disagree with `annotations.category`
  for the same URI. Not consumed by the app today (`app.js` filters on
  `annotations.category`), so this is a latent trap rather than a bug.

- **`webapp/app/app.js:592-594`** — scripture cards no longer show `itemTitle` in the meta
  line (the removed `if (ann.itemTitle && ann.kind === "scripture")`). Not mentioned in the
  requirements either way; flagging it only so the behaviour change is a decision rather
  than an accident.

### Performance

- **`webapp/app/app.js:1013` → `:917`** — `refreshCards()` rebuilds `el.results.innerHTML`
  once per warm batch. If that reflow shortens the document past the current scroll position
  it fires `scroll`, which is a `noteInteraction` trigger (line 1335), which calls
  `stopWarming` and re-arms the 30 s idle timer. The comment at 913-916 shows the author knew
  about this and moved the call from per-document to per-batch, but per-batch is still every
  iteration: in the worst case warming settles into 2 documents per 30 s while any cards are
  on screen, rather than 2 per 500 ms. Not a spin or a leak — the generation counter at
  `:977` correctly prevents double-running loops, and I could not construct a case where two
  loops run concurrently or where the loop busy-spins — but the throughput ceiling is real
  and would take a very long time to warm ~1,133 documents.

### Note, not a finding

- **`webapp/gospel_content.py:34` (R1 anchor rule)** — exactly one real highlight entry in
  the export, `/scriptures/bofm/3-ne/17.8` (annotation `c6cfff82…`, its only highlight, no
  note), has an anchor that does not start with a letter and is therefore dropped by
  `HIGHLIGHT_URI`. The old regex rejected it too (it was one of the 3,005 dropped rows), so
  this is not a regression — the annotation is now *retained* as a `document` in the
  Scriptures bucket, showing "No paragraph content at this reference." The R1 tradeoff is
  explicitly what the spec asked for; recording it here only because it is undocumented and a
  future reader will wonder.

---

## What I checked and found correct

Called out because the task asked about these specifically and a clean result is a result:

- **`dev_server.py` write-back.** Loopback bind (`:152`); path restricted to
  `^/_cache/[0-9a-f]{64}$` with no filesystem path derived from it (the filename comes from
  `sha256(doc["uri"])`, `gospel_content.py:292`, so traversal is structurally impossible);
  `Host` must name loopback (DNS-rebinding defence, `:56`); `Sec-Fetch-Site` / `Origin`
  cross-site rejection (`:66-74`) with the `Origin`-only fallback correct for browsers that
  omit fetch metadata; body cap enforced *before* the read (`:81`); strict schema validation;
  allow-list **fails closed** on a missing DB, an unreadable DB, and a pre-feature schema
  (`load_known_uris`, and `KnownUris` tests). R34/R34a fully met, and `safe_url` correctly
  rejects `javascript:`, `data:`, protocol-relative and relative URLs.
- **Retention and the referenced-paragraph filter.** `referenced_anchors` collects *both*
  anchors and Pids in the pre-pass, and the embed filter at `build_data.py:449` accepts a
  paragraph under either — so a renumbered paragraph found by Pid is not dropped by the
  "referenced only" rule. Verified by reconciliation, not just by reading.
- **Pid vs para_id agreement between build and runtime.** `parse_document_highlights:333`
  (`by_pid.get(pid) or by_para.get(para_id)`) and `resolveParagraph` in `app.js:558-562` use
  the same precedence, and the build writes the *resolved* paragraph's `para_id`/`pid` into
  the highlight row (`:350`) so both sides agree on what was matched.
- **XSS.** Every interpolation into `innerHTML` in `app.js` goes through `escapeHtml`,
  including attribute values (`data-tag`, `data-type`, `data-open`, the `href`). `escapeHtml`
  escapes both quote characters, so no attribute breakout. The one `href` built from
  untrusted-ish input is either `safe_url`-filtered on the Python side or constructed by
  prefixing `CONTENT_ORIGIN`.
- **No scripture regression.** `highlights` queries are split on `book_id IS NOT NULL` /
  `doc_uri IS NOT NULL`; the chapter reader is unchanged; `/` and `Esc` handling is
  byte-identical to the baseline; `test_scripture_highlights_did_not_regress` pins 9,162
  scripture highlight rows and passes.
- **Warming loop.** Generation counter prevents a second loop starting beside a parked one;
  `warmAttempts` bounds per-document retries; `warmFailures` implements "3 consecutive"
  correctly (one success anywhere in a batch resets it); offline/metered/idle gates all
  present; the 500 ms spacing means no busy-spin is possible even in a pathological case.
- **`build_data.py` never touches the network** — asserted with sockets disabled (R10), and
  by inspection it has no HTTP imports.

## Merge recommendation

**Safe to merge.** Nothing found is blocking: there is no security defect, no data loss, no
crash path, no regression to existing scripture behaviour, and the two numeric acceptance
criteria (R3's 6 dropped rows and R4's 5,721 / 3,132 / 614) reconcile exactly against the
real export. The tests are real tests — they assert the requirements rather than restating
the implementation — and they pass.

The four Medium findings are all "a required UI state or classification rule is not quite
what the spec says", not "the change is unsafe". My suggested ordering:

1. **Fix before merge if anything is** — M1 and M2 (`app.js`): move the `restricted` check
   above the `isCached` early return, and drop the `passages.length !== missing.length` gate
   so the total-miss and `empty` cases get the same label the card already produces. Both
   are a few lines and remove the only user-visible "blank panel" in the change.
2. **Fix soon, in a follow-up** — M3 (a `restricted` column on `documents`, otherwise M1's
   fix still degrades after a rebuild) and M4 (decide `/manual` fallback: Other per R6/R7, or
   amend R7 — and stop `CategoryName` overriding the FTSOY slug).
3. **Track, don't block** — R21's measurement (`DOCUMENT_OFFSET_SHIFT` is still `None`).
   The requirement's own guard — "until measured, non-scripture partial-paragraph rendering
   must not ship" — is honoured, whole paragraphs render, and a test pins the `None`. The
   feature is simply incomplete rather than wrong, and it cannot be completed until the cache
   has been filled by real browsing, which merging is a prerequisite for.
