# Implementation notes — cycle 4 (R15/R24 whole-talk General Conference)

122 tests pass, up from 106. Scope was R15, R15a, R24, R24a, R24b, R40a, R50 and Open
question 5 answered as (b). Search was **not** widened — option (c) was explicitly rejected,
so `refreshContentText` is untouched.

## What changed, file by file

**`gospel_content.py`** — added `GC_PREFIX` and `stores_whole_document(uri)`. The rule gets
one home because three writers and one reader depend on it; a split-brain answer would
store one thing and render another. `build_alignment.py` now imports `GC_PREFIX` from here
instead of defining its own copy.

**`build_data.py`** — the paragraph-embedding filter gains `keep_all` from
`stores_whole_document`. `referenced_anchors()` is unchanged and still governs every other
namespace; this is deliberately a one-line widening rather than a restructure, because the
Pid-matching branch beside it is subtle and was itself a cycle-3 bug fix.

**`tools/build_alignment.py`** — both GC writers now store whole talks (R40a):
- the archive path iterates `mapping` instead of `needed`. R15a is the hard bound here: a
  corpus paragraph the alignment never resolved has no `para_id`, and inventing one would
  file text under an id the live page uses for something else.
- `write_fetched()` (the rejected-talk fallback) stores every extracted paragraph. `needed`
  is no longer a filter, so rather than leave an unused parameter it now reports anchors
  absent from the live page — a real signal, since those highlights will not land.

**`app/app.js`** — `state.paragraphsByDoc` (docUri → records in sort order), maintained in
both the build-load and `adoptParagraphs` paths; `documentPassages` now exposes the resolved
`record`; new `documentContext()` and `stateStoresWholeDocument()`; `renderDocumentBody`
renders context mode and scrolls to the first `.focus`.

**`app/styles.css`** — `.reader-body .verse.context { color: var(--muted) }`. Context is
*recessed* rather than emphasis being *added*, so the annotated paragraph reads as normal
text and `.focus`'s existing accent background stays distinct from a `<mark>` highlight.

**`tests/`** — `test_reader_js.py` is new (9 tests); `test_build_data.py` and
`test_alignment.py` extended.

## Reusing the scripture mechanism, as R24 requires

`documentContext` returns records tagged `focus`, `renderDocumentBody` emits
`class="verse focus"`, and the scroll is the same `querySelector(".verse.focus")` +
`scrollIntoView({block:"center"})` the chapter reader already used. No second mechanism, no
new CSS class for emphasis — `.context` is the only addition and it styles the *unemphasised*
side.

Focus is matched on the **resolved record**, not on `para_id`. A renumbered page resolves
through Pid, so comparing ids would emphasise nothing on exactly the documents where R18
matters. `test_focus_follows_the_pid_when_the_page_was_renumbered` covers it.

## Corner cases → tests

| Corner case | Test |
|---|---|
| GC talk stores all paragraphs; non-GC does not, **in one build** | `test_namespace_split_holds_within_one_build` |
| GC whole-talk embedding | `test_general_conference_embeds_the_whole_talk` |
| Non-GC still referenced-only | `test_only_referenced_paragraphs_are_embedded_outside_conference` |
| Pid-matched paragraph survives the non-GC filter | `test_referenced_paragraph_is_kept_under_its_new_number` |
| Whole talk renders, one paragraph emphasised | `test_conference_reader_renders_the_whole_talk_with_one_focus` |
| Context paragraphs carry no highlights | `test_context_paragraphs_carry_no_highlights` |
| Renumbered page — emphasis follows Pid | `test_focus_follows_the_pid_when_the_page_was_renumbered` |
| Several annotated paragraphs | `test_every_annotated_paragraph_is_focused` |
| Non-GC namespace never gets context | `test_non_conference_never_gets_context` |
| Pre-R15 referenced-only cache renders as before | `test_referenced_only_storage_renders_as_before` |
| Gapped storage not rendered as a talk | `test_gapped_storage_is_not_rendered_as_a_talk` |
| Every anchor misses — talk still renders as context | `test_context_still_renders_when_every_anchor_misses` |
| **Card does not grow to the whole talk (R24b)** | `test_card_passages_do_not_grow_to_the_whole_talk` |
| Rejected talk stores whole page (R40a) | `test_stores_the_whole_talk_not_only_the_anchors` |
| Rejected talk whose anchor is gone | `test_reports_but_keeps_a_talk_whose_anchor_is_gone` |
| Empty page writes nothing | `test_empty_page_writes_nothing` |

## Testing JavaScript without a toolchain

R51 forbids a bundler or npm, and roughly half this change is in `app.js` — the exact gap
cycle 3 flagged and that a real bug (document highlights never rendering) then walked
straight through. `test_reader_js.py` extracts the pure functions from `app.js` by name,
brace-matched, and evaluates them in `node -e` against a stub `state`. Node is already a
project dependency (`node --check` runs on both JS files), so this adds no tooling. It skips
when node is absent.

The extraction is not a parser. It would break on an unbalanced brace inside a string or
comment in one of the six functions it pulls, which is why it asserts the function was found
and node's exit status is checked rather than the output being parsed blindly.

## Added mid-cycle: the reader shows every highlight on the talk

Raised by the owner during implementation, and it turned out to be an
**inconsistency with the scripture reader rather than a new feature**:
`openChapterReader` has always queried every highlight in the chapter and used `focus` only
for the opened annotation's verses, while the document reader only ever rendered the
highlights of the annotation that opened it.

Now `state.docHighlightsByDoc` (docUri → every highlight from every annotation) backs
context mode, and emphasis stays tied to the opened annotation. It matters:
**260 of 461 talks carry more than one annotation, and one carries 15** — previously
14 of those 15 marks were invisible when opening the talk through any single one.

Scope: context mode only, so General Conference. The non-GC reader still renders only the
opened annotation's highlights, matching R24's unchanged clause for other namespaces. That
is arguably the same inconsistency in a narrower place, but widening it was not asked for
and would change every namespace's reader.

**This needs a requirements amendment.** R24 as written says "paragraphs tied to the open
annotation are visually emphasised" and says nothing about whose highlights render; the
behaviour now implemented is a deliberate superset. I did not edit `requirements.md` — it
is read-only to this phase — so it is flagged here for the orchestrator.

Tests: `test_shows_highlights_from_other_annotations_on_the_same_talk`,
`test_two_annotations_on_one_paragraph_both_render`, and
`test_unannotated_context_paragraphs_carry_no_highlights` (renamed, since "context
paragraphs carry no highlights" is no longer true — only *unannotated* ones do).

## Judgment calls

**Whole-talk mode is inferred, not stored.** `documentContext` returns null unless the
document holds strictly more paragraphs than the annotation references *and* their `sort`
values are contiguous. The alternative was a `complete` flag on the cache document and a
`documents` column. I chose inference because R24a states the contiguity rule directly, and
because a stored flag can disagree with the paragraphs actually present — a flag that lies
is worse than a check that is occasionally conservative. The cost: an archive talk whose map
missed one middle paragraph renders in the old annotated-only mode rather than showing a
gap. That is R24a's stated preference, but it is a real loss of the feature on those talks.

**Gaps fall back rather than rendering a marker.** I considered rendering the whole stored
set with a visible "…" between non-adjacent paragraphs, which would satisfy "must not imply
they are contiguous" while still showing context. R24a's wording ("renders exactly as it
does today") pointed the other way, so I took the literal reading. If the gap-marker version
is wanted it is a small change to `documentContext` plus one CSS rule.

**A GC bare-reference bookmark still shows "No paragraph content at this reference"** rather
than the talk. `openDocumentReader` early-returns when `passages.length === 0`, before
context is computed. Showing the talk would arguably be better, but that early return is
R26's `reference` state and changing it is outside this cycle's scope. Flagged, not changed.

**`.focus` on top of a whole-paragraph highlight.** With R21 unmeasured, an annotated
paragraph is entirely `<mark>`-ed *and* carries `.focus`'s accent background. They remain
distinguishable (mark colour vs paragraph background), and recessing the context text is
what actually carries the signal. This gets cleaner once R21 lands and highlights become
partial.

## Not done, and why — read this before reviewing R40a and R50

**1. 66 GC talks still hold only referenced paragraphs.** The archive path was upgraded by a
replay run (no network): 395 documents, 14,282 paragraphs, mean 36.2 — matching R15's
predicted 34.8. The remaining 66 are `source: "fetched"`, written by the rejected-talk
fallback, and their cache documents hold only the annotated paragraphs (mean 9.2). Upgrading
them needs the live page again — roughly 66 network requests. I did **not** run it: it is
outward-facing, and the instruction was to say so rather than do it silently. The reader
falls back correctly for these per R24a, so nothing is broken; R40a is simply unmet for 66 of
461 talks until someone runs it.

**2. R50 is nearly breached, and completing item 1 would breach it.** The rebuild is
**29.9 MB** against R50's 30 MB investigate-threshold and its ~27.5 MB expectation. The
estimate was low because it counted text only: `paragraphs` is 5.88 MB of rows plus 1.96 MB
of indexes across 14,887 rows, against ~1.1 MB at 2,069. Adding the 66 talks (~2,000 more
paragraphs) would put the dataset over 30 MB.

This is a genuine conflict between R40a and R50, not a rounding problem, and I have not
resolved it unilaterally. The obvious headroom is `annotations.note_html` — 1.24 MB, stored
and never read by `app.js` (`note_text` is what renders). Dropping it would cover the
overrun with room to spare, but it is a schema change and both the decision and R50's
threshold are the owner's to make.

**Coverage is not measured in this project** and I did not add a coverage tool.
