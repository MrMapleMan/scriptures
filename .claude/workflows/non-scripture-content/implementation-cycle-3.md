# Implementation notes — cycle 3 (review-cycle-2 fixes)

105 tests pass (was 93). Both High findings were correct and are fixed; the two security
findings and the significant correctness/performance ones are fixed. Coverage is not
measured in this project.

## High findings — both real

**H1: R15 was not implemented at all.** Every paragraph in a cache document was embedded,
not only referenced ones. The reviewer was right that `parseParagraphs` ships the whole
page and `build_data.py` embedded all of it — and right that my own cycle-1 test comment
("only referenced paragraphs are stored") asserted something no code did.

Fixed with a `referenced_anchors()` pre-pass, needed because a document's row is written
when its *first* annotation is seen, before the rest have been read. **My first attempt was
wrong and my own new test caught it**: filtering on anchor ids alone dropped a paragraph
that only matched via `Pid` (the renumbered-page case). The pre-pass now collects both
anchor ids and Pids. Verified: a 20-paragraph cache document with one annotation now
embeds 1 row; 25 real cached documents produce 112 paragraphs, ~4.5 per document, matching
the measured mean.

**H2: R18 was implemented only in the build.** At runtime `documentPassages` looked up by
`para_id` only, so the Pid fallback never ran — on the *normal* path, since almost every
document is `unfetched` at build time and is resolved against a freshly fetched page.

Fixed with a `state.paragraphsByPid` index and a `resolveParagraph()` used by both
`documentPassages` and `refreshContentText`. Passages are now grouped by the paragraph
actually resolved, so two anchors that turn out to be the same renumbered paragraph do not
render it twice.

## Security

- **DNS rebinding** — `Sec-Fetch-Site: same-origin` is satisfied by a rebound hostile
  origin. Now also requires `Host` to name loopback. Tests:
  `test_rejects_non_loopback_host_header`, `test_accepts_loopback_host_variants`.
- **`postBack` to any origin** — the sharper finding of the two. On a static host every
  fetched document was POSTed in full to that host, disclosing which talks and manuals the
  user annotated, contrary to R49. Now sent only from loopback. README corrected: it
  previously described this as "simply fails there and is ignored", which was the mistaken
  assumption behind the code.

## Also fixed

- **Redundant re-fetch** on every open of a bare `reference` bookmark or a cached document
  whose anchors all missed — the early return required a resolved passage.
- **Two concurrent `warmLoop`s**: a loop parked on `await Promise.allSettled` could not be
  stopped, so the idle timer started a second one beside it. A generation counter now
  retires the old loop, checked again after the batch settles.
- **`warmFailures`** incremented by batch size, making "3 consecutive" mean 2 batches.
- **`refreshCardsFor` → `refreshCards`**, once per batch instead of per document. It
  rebuilt every visible card, and rebuilding changes page height, which fires `scroll`,
  which counts as interaction — the feature was pausing itself.
- **Focus loss**: `renderCategories` rewrote `innerHTML` on every filter pass, so toggling
  a checkbox by keyboard dropped focus to `<body>`. Now updates in place when the bucket
  set is unchanged.
- **R40 archive labelling** — genuinely missing, as reported. Cache documents carry
  `source` (`fetched` | `archive`), `documents` has a `source` column, and the reader says
  "Shown from your local archive, not the live page".
- **Reader errors no longer mark a document permanently failed** — only 404/410 do.
- **`contentPendingLabel`** claimed "not downloaded" for a cached document whose anchors
  missed; it now says so.
- **Export download** — anchor now attached to the document and the blob URL revoked on a
  later tick.
- **`index.html`** shipped the label "Select none" that `renderCategories` immediately
  overwrote.
- **README** said 3,133 / 613; the real build is 3,132 / 614. Corrected, and the anchor and
  write-back sections rewritten to match the code.

## New test file

`tests/test_real_export.py` asserts the numeric acceptance criteria the reviewer correctly
identified as unasserted — R3 (exactly 6 dropped), R4 (kind counts within 1%), totals
reconciling to 9,473, no uncategorised rows, `/journal` not a document, non-`pN` anchors
captured, and scripture highlights unchanged at 9,162. It builds against the real export
and **skips** when that export is absent, since it is personal data and gitignored. No
network.

That last assertion is the one I would keep if I could keep only one: it is what would
catch a future change to the retention rules silently moving thousands of annotations.

## Judgment calls

**`warmAttempts` is not persisted.** A document that fails three times is retried on the
next page load. Persisting it would need another IndexedDB store and a policy for when to
forget; a reload is a reasonable reset for a transient-failure counter.

**The `Host` check hardcodes loopback names rather than comparing to the bind address.**
`serve.sh` always binds `127.0.0.1`, and accepting a hostname the user configured would
reintroduce the rebinding hole. If someone wants to serve on a LAN address this refuses,
deliberately — R52 calls the endpoint a local-only affordance.

**Not fixed, and I disagree with the framing** — the reviewer's Low finding that a
`/journal` row with no note is dropped, contradicting R3. It is correct that the clauses
conflict, but such a row has no note, no verse, and no readable source: there is nothing to
render. Dropping is right; R3's wording is what is imprecise. Flagging rather than silently
"fixing" either side. It does not affect the count — the 6 dropped rows have no URI at all.

**Still outstanding, unchanged across all three cycles:** R21's offset measurement needs a
filled cache and has not been run, so `DOCUMENT_OFFSET_SHIFT` stays `None` and bounded
non-scripture highlights tint the whole paragraph. The tool is written and the fallback is
spec-compliant and tested. This is the one requirement deliberately left undelivered, and
it needs the user to browse (or warm) enough content first.
