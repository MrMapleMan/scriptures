# Implementation notes — cycle 2 (review fixes)

Addresses the findings in `review-cycle-1.md`. 93 tests pass (was 73); every fix has a test
that would have caught the original defect. Coverage is not measured in this project.

## Both High findings were correct, and one was upstream of the other

**High-2 (anchor shapes) was the root cause, and High-1 was largely its symptom.**
`HIGHLIGHT_URI` only accepted `<uri>.p<N>`. Verified against the real export: **574 of
14,225 highlight entries** use other shapes — `title29` (191), `aside2_p1`, `figure1_p29`,
`study_summary1`, `kicker1`, and opaque ids like `p_iilzI` in talks from 2025 on — and
**every one carries a `Pid`**. I fetched samples of each: all sit on `<p>` or `<h3>` with a
`data-aid`, so only the *id pattern* was wrong, not the tag set.

Fix: anchors are `[A-Za-z][\w-]*`, required to start with a letter so a handbook section
number (`/handbook/…/8.1`) is not mistaken for one. `VERSE_ANCHOR` (`^p(\d+)$`) now gates
the scripture path, which previously would have crashed on `int("tudy_summary1")` had a
scripture heading anchor reached it.

Measured effect on the real build:

| | before | after |
|---|---:|---:|
| document highlight rows | 4,489 | **4,901** |
| document annotations with no highlight at all | 273 | **70** |
| verse highlight rows | 9,162 | 9,162 (unchanged) |

The 70 remaining are genuine bare `reference` bookmarks with no anchor — correct, and they
render as metadata-only cards.

**High-1 (classification).** With anchors generalised, only **71** URI rows have no
parseable anchor, not the ~135 the review inferred. The reviewer's specific complaint was
right though: `/journal` was becoming a `document` with a reader offering to fetch content
that cannot exist. Fixed by routing URIs whose bucket is *My Notes* to `kind='note'`.

I did **not** adopt the strict "must have a paragraph-suffixed highlight" reading. It would
drop bare `reference` bookmarks to real pages, which the requirements' own edge-case table
says must be retained as metadata-only cards. Final counts: 5,721 / 3,132 / 614 / 6 dropped
— and I amended R2, R4 and R7 rather than bending code to stale estimates. **This reverses
my cycle-1 note**, which asserted R4 was simply wrong and moved on; the requirement was
genuinely ambiguous, and leaving it unamended is what let two readings coexist.

## Security fixes

- **Fail-open allow-list** (`dev_server.py`): `if self.known_uris and …` meant an empty list
  disabled the check. Now fails closed, and startup prints `write-back DISABLED` when the
  dataset has no `documents` table. Test: `FailsClosed.test_empty_allow_list_refuses_everything`.
- **Cross-site writes**: a simple-content-type POST is not preflighted, so any page the user
  was browsing could write into the cache while `serve.sh` ran. Now requires
  `Sec-Fetch-Site: same-origin`, falling back to an `Origin`/`Host` comparison for browsers
  that do not send fetch metadata. Tests: `test_rejects_cross_site_requests`,
  `test_rejects_foreign_origin_when_fetch_metadata_absent`, `test_accepts_same_origin_request`.
- **`javascript:` in `canonical_url`**: new `safe_url()` keeps only `http`/`https`. Tests:
  `SafeUrl.*`, including `test_stripped_from_a_cache_document`.

## Correctness fixes

- **R19 shortcut** — `norm_text(text) if "<" in text else text.strip()` skipped entity
  decoding and NFC for markup-free text. Now unconditional.
  Test: `test_text_is_always_normalised_even_without_markup`.
- **"Select none" was a no-op** — both branches produced an empty set. The reset is now
  hidden unless a filter is active, and reads "Select all".
- **Reader said "No readable text at this source"** for an annotation with no anchors. Now
  distinguishes that from a page that genuinely has no text.
- **`build_alignment.py` replay** derived `sort` from the number in `para_id` (forbidden by
  R14) and discarded `pid`. The learned map now stores DOM order and pids.
- **Warming**: added the metered/`saveData` check, made the toggle schedule the idle delay
  instead of starting immediately, made "3 consecutive failures" actually consecutive
  (a mixed batch resets), and replaced permanent `failed` marking with a per-document
  attempt counter so a flaky connection does not retire documents for the session.
- **`adoptParagraphs`** merged instead of replacing, so a paragraph dropped by a newer
  revision kept stale text. Now replaces the document's set.
- **`fetch_state='failed'` was unreachable.** Cache documents may now carry `error`, the app
  records 404/410 as permanent, and the build reads it into `fetch_error`.
  Test: `test_cached_document_with_an_error_is_failed`.
- **Cards left stale after background warming** — `refreshCardsFor` now runs on warm success.
- **`warmCandidates`** used `Array.includes` in a scan of 9,467 annotations, per iteration.
  Now a `Set`.
- **`CONTENT_CACHE` unbounded** — trimmed to the 300 most recent entries.
- **`unpack_export.py`** raised `TypeError`/`AttributeError` on a string version or a
  non-dict element; both are now handled.
- **Corpus path quoting** — `.replace(" ", "%20")` replaced with `urllib.parse.quote`.

## The NUL bytes

`paraKey` joined with a literal `\x00`, which made `app.js` binary to git: the diff showed
`Bin 26800 -> 45952 bytes` and nothing else. **The entire change was unreviewable and I did
not notice.** Replaced with the escape sequence `"\x1f"`; the diff is now 572 insertions /
66 deletions. Worth remembering that "tests pass" said nothing about this.

## Judgment calls

**Anchor extraction is now deliberately over-broad.** `extract_paragraphs` accepts any
`[A-Za-z][\w-]*` id, so footnote containers get extracted too. Harmless — only paragraphs an
annotation references are ever stored (R15) — and the alternative is another allow-list that
would need updating every time the Church adds a component. The old test asserting `note1`
is skipped was updated rather than preserved; that assertion encoded the bug.

**Cross-site defence uses `Sec-Fetch-Site` with an `Origin` fallback, not a token.** A CSRF
token would mean state and a handshake in a dev-only server. Every browser that can run this
app sends fetch metadata; the `Origin` branch covers the rest. A non-browser client can
forge either, but it could equally write the file directly — the threat model here is a web
page the user visits, not local code.

**404/410 are recorded as permanent; other statuses are not.** A 500 or a timeout is
transient and stays retryable. This is what makes the retired Handbook 2 (2 documents, 18
annotations) stop being re-fetched every build, without freezing anything that might recover.

**Still not done, unchanged from cycle 1:** `DOCUMENT_OFFSET_SHIFT` remains `None`, so
document highlights render whole-paragraph until `measure_offsets.py` runs against a filled
cache (R21 forbids shipping a guess). And R40's corpus fallback is served through the build,
not at runtime — an 89 MB corpus cannot ship to the browser. If a runtime path was intended,
it needs a different design and I have not guessed at one.
