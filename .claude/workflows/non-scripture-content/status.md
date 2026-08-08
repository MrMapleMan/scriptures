# Workflow status: non-scripture annotation content

Artifacts: `/home/henri/github/scriptures/.claude/workflows/non-scripture-content/`

Baseline `2e92ce3` on branch `sql`. Tree was clean at start (only untracked `.claude/` and
the unrelated `tmp/g3logPython` clone), both excluded from diff scope.

## Requirements — done
`requirements.md` — via the `requirements` skill, derived from `plan.md` and reviewed for
gaps. Amended twice in place during the workflow, each amendment marked inline:
- **R1** — anchors are not all `p<N>`; 574 real highlight entries use other shapes.
- **R2 / R4** — the `document` rule and its expected counts. The original estimate
  (~2,999 / ~753) counted only *dropped* rows with a URI and missed the ~135 previously
  kept as notes. Corrected to **5,721 / 3,132 / 614**.
- **R7** — resolved a Youth-bucket contradiction against R8's authoritative list.
- **R19** — normalisation is unconditional, no "looks like plain text" shortcut.
- **R34 / R34a** — allow-list must fail closed; cross-site writes rejected; `canonical_url`
  restricted to http/https.

## Implementation — done, 3 cycles
Notes: `implementation-cycle-1.md`, `implementation-cycle-2.md`, `implementation-cycle-3.md`

**8 files changed, 10 added** (1,321 insertions / 226 deletions at cycle 3 scope):
`build_data.py`, `app/app.js`, `app/index.html`, `app/styles.css`, `app/service-worker.js`,
`serve.sh`, `README.md`, `.gitignore`; new `gospel_content.py`, `dev_server.py`,
`tools/{measure_offsets,build_alignment,unpack_export}.py`, and five test modules.

**106 tests, all passing** — the project's first. Includes `test_real_export.py`, which
asserts the numeric acceptance criteria against the real export and skips when that
(gitignored, personal) file is absent.

## Project checks — all pass
No lint, typecheck, or CI exists in this project; the full available gate is:

```
python3 -m unittest discover -s tests   → Ran 106 tests, OK
python3 -m py_compile  (all py)         → OK
node --check app.js, service-worker.js  → OK
bash -n serve.sh                        → OK
NUL-byte / mojibake scan                → clean
```

End-to-end verified against real data: clean build → `5721 scripture, 3132 document,
614 note, 6 dropped` (R3/R4 exactly); dev-server write-back → cache → rebuild embeds the
paragraph with its Pid intact; `build_alignment.py --learn` verified 25/25 talks, and
replay regenerated them with `urllib.request.urlopen` sabotaged, proving it needs no network.

## Review — cycle 3 of 3
Isolated subagent: **yes**, a fresh one each cycle. Reviewer skill invoked: **yes**, all
three confirmed it explicitly.

| cycle | Critical | High | Medium | Low | report |
|---|---:|---:|---:|---:|---|
| 1 | 0 | 2 | 10 | 11 | `review-cycle-1.md` |
| 2 | 0 | 2 | 7 | 12 | `review-cycle-2.md` |
| 3 | 0 | 0 | 6 | 10 | `review-cycle-3.md` |

Cycle 3's explicit verdict: **"Safe to merge."** No security findings; it stated
`dev_server.py` — the component that writes disk from an HTTP body — was the strongest part
of the change and it could not break it.

All four cycle-3 Medium findings were then fixed and re-verified (restricted-state reader
ordering, missing reader notices, `documents.restricted` persistence, and the `/manual`
fallback so R7's table matches exactly, now pinned by a test).

### Findings that landed on a recorded assumption

- **Cycle 1, H1** contradicted my cycle-1 note claiming R4's counts were simply wrong. The
  reviewer was partly right: the requirement was genuinely ambiguous, and cycle 2 amended
  R2/R4 rather than leaving two readings to coexist. Recorded as a reversal in cycle 2's notes.
- **Cycle 2, H1** contradicted a test *comment* I had written asserting behaviour no code
  implemented ("only referenced paragraphs are stored"). Fixed, and my own new test then
  caught a bug in the fix.
- **Cycle 1** found two literal NUL bytes that made `app.js` binary to git — the entire
  500-line change was unreviewable and passing tests said nothing about it.

## Verdict — Ready with noted findings

Merge-ready. No Critical or High findings survive, no security defects, no data loss, no
regression to scripture behaviour (`test_scripture_highlights_did_not_regress` pins 9,162
rows). **3,005 previously discarded annotations are now retained**, dropping only 6.

Outstanding, deliberately:

1. **R21 is not delivered.** `DOCUMENT_OFFSET_SHIFT` remains `None`, so bounded
   non-scripture highlights tint the whole paragraph. R21 forbids shipping a guessed shift,
   and `tools/measure_offsets.py` needs a filled cache that only real browsing produces —
   merging is a prerequisite for completing it, not the other way round. The fallback is
   spec-compliant and tested.
2. **No JavaScript tests.** Roughly half the new logic is in `app.js` and the project has
   no JS harness; R51 forbids adding a build toolchain. The Python side is well covered,
   the browser side is not. Flagged by cycle 3 and worth a decision.
3. **Dataset is 22.0 MB**, against R50's ~20 MB estimate — that estimate predated retaining
   3,000 more annotations. `note_html` (1.24 MB) is stored but never read by the app;
   removing it is a schema change R9 forbids, so it is flagged rather than done.
## Post-review fix — document highlights never rendered

Found by the owner in real use, not by any of the three review cycles.

`parse_document_highlights` writes `word_start`/`word_end` as NULL when the paragraph text
is not available at build time — which is every document but one, since a document is
normally `unfetched` when the dataset is built. Nothing ever filled the span in once the
page was fetched at runtime, and `renderPassage` skipped spanless highlights, so a fetched
document rendered as plain untinted text. Verified against the real data: all 7 highlight
rows for `/general-conference/2003/10/the-grandeur-of-god` had NULL spans.

Fixed with `spanHighlights()` in `app.js`, applying at runtime the same rule
`build_data.py` applies when it *does* have the text (`DOCUMENT_OFFSET_SHIFT is None`
→ tint the whole paragraph). Also changed `renderPassage`'s `!h.s || !h.e` guard to an
explicit null comparison, so a legitimate word offset of 0 is not discarded once R21 is
measured.

This is the concrete cost of item 2 above: the rule was tested on the Python side and
unreachable there, while the runtime path that actually executes it had no test at all.

4. **One export row is unreachable by design:** `/scriptures/bofm/3-ne/17.8` has an anchor
   starting with a digit, excluded so handbook section numbers aren't misread. It is
   retained as a document, showing "No paragraph content at this reference."
