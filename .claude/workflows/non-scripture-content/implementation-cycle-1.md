# Implementation notes — cycle 1

Against [`requirements.md`](requirements.md). All 73 tests pass
(`python3 -m unittest discover -s tests` from `webapp/`). Coverage is not measured in this
project and no coverage tool was added.

## What changed, file by file

**`webapp/gospel_content.py` (new).** Shared pure logic: `norm_text`, `extract_paragraphs`,
`classify`, and the cache read/write/validate helpers.

Structured as a separate module rather than living in `build_data.py` because three
callers need it (the build, the dev server, both tools) and because R19's normalisation
rule is only meaningful if every caller applies it identically — the investigation that
produced this plan lost 12 of 119 anchors to exactly that inconsistency. A shared helper
makes the rule enforceable instead of conventional.

**`webapp/build_data.py`.** New `documents`/`paragraphs` tables; `annotations` gains
`kind='document'`, `category`, `doc_uri`, `subtitle`; `highlights` gains
`doc_uri`/`para_id`/`pid` and its verse columns become nullable. Retention rewritten,
`parse_highlights` split into `parse_verse_highlights` and `parse_document_highlights`, and
the offset arithmetic factored into `clamp_span` so both paths share the clamp/swap rules.

**`webapp/dev_server.py` (new)** + **`serve.sh`.** `SimpleHTTPRequestHandler` subclass
serving `app/` plus `POST /_cache/<sha256>`.

**`webapp/app/app.js`.** Document cards and reader, IndexedDB, runtime fetch with an
in-flight map, idle warming, category checkboxes, the Show-control split, export.

**`webapp/app/index.html` / `styles.css` / `service-worker.js`.** New controls; `.byline`,
`.unfetched`, `.doc-link`, `.type-list`, `.field.disabled` styles; a runtime cache route
scoped to the content API and `CACHE` bumped to v4.

**`webapp/tools/{measure_offsets,build_alignment,unpack_export}.py` (new).**

**`webapp/tests/{test_gospel_content,test_build_data,test_dev_server,test_alignment}.py`
(new).** First tests in this project.

**`webapp/README.md`**, **`.gitignore`** (`webapp/.cache/`).

## Corner case → test

| Corner case | Test |
|---|---|
| Entity-encoded text compared across sources | `NormaliseText.test_decodes_html_entities` |
| Decomposed vs precomposed Unicode | `NormaliseText.test_composes_unicode_to_nfc` |
| Anchor on a heading, not a `<p>` | `ExtractParagraphs.test_includes_headings` |
| Non-contiguous / non-monotonic ids | `ExtractParagraphs.test_sort_follows_dom_order_not_id_number`, `Align.test_non_contiguous_ids_still_map_by_position` |
| Unknown URI namespace | `Classify.test_unknown_root_falls_to_other_never_dropped` |
| `CategoryName` disagreeing with the URI | `Classify.test_category_name_is_only_a_tiebreaker` |
| Preach My Gospel overriding its own CategoryName | `Classify.test_preach_my_gospel_overrides_category_name` |
| Corrupt / hash-mismatched cache file | `CacheRoundTrip.test_corrupt_file_is_skipped_not_fatal`, `test_hash_mismatch_is_skipped` |
| Re-importing the same export twice | `CacheRoundTrip.test_write_is_idempotent`, `Endpoint.test_repeated_post_is_idempotent` |
| Talk annotation (previously dropped) | `Retention.test_conference_talk_is_kept_as_document` |
| URI, no note, no highlights (the 82 reference-only docs) | `Retention.test_uri_without_note_is_retained_not_dropped` |
| Chapter heading / JST / BD / OD | `Retention.test_scripture_uri_with_unresolvable_verse_becomes_document` |
| The 6 genuinely empty rows | `Retention.test_row_with_no_uri_no_note_no_verse_is_dropped` |
| Content revised, `Pid` still valid | `Documents.test_pid_wins_over_para_id` |
| Anchor absent from current content | `Documents.test_anchor_missing_from_content_keeps_row_without_span` |
| 0-paragraph document | `Documents.test_cached_document_with_no_paragraphs_is_empty_not_failed` |
| Offsets: `-1`, clamp, swap, `word_count+1`, empty text | `ClampSpan.*` (6 tests) |
| Build with no connectivity (R10) | `NoNetwork.test_build_makes_no_network_connection` |
| Path traversal / unknown endpoint | `Endpoint.test_rejects_path_traversal`, `test_rejects_unknown_path` |
| URI not in the dataset | `Endpoint.test_rejects_uri_not_referenced_by_the_dataset` |
| Oversized / malformed body | `Endpoint.test_rejects_body_over_the_cap`, `test_rejects_malformed_json` |
| Byline absent from the corpus | `Align.test_leading_byline_is_synthesised_from_columns` |
| Corpus dropped a heading | `Align.test_dropped_paragraph_is_simply_unmapped` |
| Corpus DB absent entirely | verified manually; the tool prints "unavailable" and exits 0 |

## Verification beyond unit tests

- Real build: **6 dropped of 9,473** (R3 exactly). Kinds 5,721 / 3,133 / 613.
- All 13 SQL statements `app.js` issues were executed against the built schema — 13/13 ok.
- `node --check` on `app.js` and `service-worker.js`.
- Full round trip: `dev_server` POST → `.cache/documents/` → rebuild → paragraph embedded
  and the highlight anchored at `p25`/`pid=152799681`, `word_start..end = 1..10`. An
  unknown URI was refused with 403.
- `build_alignment.py --learn --limit 6`: 6 verified, 0 rejected. Replay mode then
  regenerated all 6 with `urllib.request.urlopen` sabotaged, proving it needs no network.

## Judgment calls the requirements did not settle

**R4's kind counts are wrong, and the implementation is right.** It predicted `document`
~2,999 and `note` ~753. Actual: 3,133 and 613. The estimate came from the *dropped* rows
that carry a URI (2,999) and forgot that ~134 previously-kept `note` rows also have URIs —
under R2 an annotation with a URI is a `document` even when it carries a note, which is
what makes its content fetchable. Total reconciles exactly: 5,721 + 3,133 + 613 + 6 =
9,473. I did not "fix" the code to hit the stated numbers.

**R50's size estimate is also stale.** It says ~18 MB → ~20 MB. The real dataset is
**21.9 MB before any paragraph text** and will reach ~24 MB when the cache fills, because
3,000 more annotations now carry their note/refs payloads. I deliberately did **not**
recover the 1.24 MB of `note_html` that the app never reads: dropping a column is a schema
change R9 forbids, and doing it silently to hit a stale estimate would be the wrong call.
Flagging it for the size decision instead.

**Requirements R7/R8 contradict each other on "Youth".** R7 routes
`/manual/for-the-strength-of-youth` to a `Youth` bucket that R8's authoritative list does
not contain. I followed R8 and the plan's checkbox table: `Youth`, `Life Help`, and
`Archived Content` all fall to **Other**, and `/manual/for-the-strength-of-youth` classifies
as **Books & Lessons** (it is a booklet, and the `/ftsoy` magazine root is separately
Magazines). Worth a second opinion.

**Preach My Gospel overrides `CategoryName` for both editions.** The owner chose Books &
Lessons; the 2023 edition's export says `Handbooks and Callings`. Applying the decision to
only the untagged edition would split one work across two buckets, so the slug rule is
ordered ahead of the handbook rule and covers both. Deliberate, and reversible in one line.

**`DOCUMENT_OFFSET_SHIFT` ships as `None`, so document highlights render whole-paragraph.**
R21 forbids partial rendering before measurement, and `measure_offsets.py` needs a filled
cache that does not exist yet. This is the one place where a *visible* feature is
deliberately incomplete: a bounded highlight on a talk currently tints the whole paragraph
rather than a span. Choosing `None` over a guess is the point — a wrong shift is silently
wrong, and silent wrongness is what the whole investigation was about.

**The `noteOnly` checkbox is gone.** R46 moves all type filtering to the checkboxes, and
"My Notes" does exactly what `noteOnly` did. Removing it avoids two controls expressing one
constraint. Not explicitly required; call it out if you want it back.

**Unticking a box while "all" is showing means "only this one".** With all-checked
displayed as the no-constraint state, the first click has to materialise a real selection.
Ticking every box back drops to no-constraint again so the badge clears.

**IndexedDB over Cache Storage for fetched content**, against the plan's original wording.
Structured paragraph rows render through the identical code path as build-embedded rows;
raw `Response` objects would need a second parse path. The service worker still keeps a
Cache Storage route for the API so an offline reload has something to fall back on.

**Warming pauses on interaction rather than throttling.** R33 required idle-gating and a
failure cap; it did not say what happens mid-batch when the user starts typing. Pausing is
the conservative reading. A document that fails is marked `failed` so the loop cannot spin
on it forever — otherwise the 404'd Handbook 2 would be retried indefinitely.

**`postBack` failures are swallowed entirely**, including on the dev server. R35 requires
that on static hosts, and distinguishing "no endpoint" from "endpoint broken" would need
the failure surfaced somewhere the user cannot act on. The export button is the fallback.

**Not implemented, and I want to flag it rather than bury it:** the reader has no
*corpus-backed* offline path yet. `build_alignment.py` puts corpus text into the cache so
it is embedded at build time, which is what makes it available offline — but the app does
not consult the corpus at runtime, because an 89 MB database cannot ship to the browser.
R40's "renders from the corpus using the stored map" is satisfied via the build, not at
runtime. If the intent was a runtime path, that needs a different design and I did not
guess at one.
