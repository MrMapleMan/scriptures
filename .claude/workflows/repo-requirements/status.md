# Workflow status: Scriptures repository — reverse-engineered requirements

Artifacts: `/home/henri/github/scriptures/.claude/workflows/repo-requirements/`

Scope note: the user asked for the requirements phase only ("scan the repo, use the
requirements skill, create a requirements document"). The development and review phases
were **not run** — there is no change to implement or review. This is a single-phase run
of `requirements`, not a full software-lead pipeline.

## Requirements — done
`/home/henri/github/scriptures/.claude/workflows/repo-requirements/requirements.md`

Invoked via the `requirements` skill (available at `~/.claude/skills/requirements`), not
degraded. Written from a direct scan of the code at commit `96a6017` (branch `sql`), not
from an interview — the source of truth for a reverse-engineered spec is the code.

Covers: 59 numbered functional requirements across the dataset build, the static server,
and the PWA's load/search/filter/read/offline behavior, plus the Python toolkit; an edge
case table; non-functional requirements; explicit out-of-scope; a known-defects list; and
8 open questions.

Files read: `webapp/build_data.py`, `webapp/README.md`, `webapp/serve.sh`,
`webapp/app/{app.js,index.html,manifest.json,service-worker.js}`,
`scriptures/{scriptures.py,scriptures_to_pickle.py}`,
`notes/{readnotes.py,read_notes_script.py,search_tags.py,url_book_dict.py}`,
`analysis/*.py`, `sandbox.py`, `test_dir/use_scriptures.py`, `requirements.txt`,
`.gitignore`, `resources/annotations/start_note_search_app.sh`.

Excluded as not part of this project: `tmp/g3logPython/` (unrelated third-party clone),
the three checked-in virtualenvs.

## Implementation — not run (no change requested)

## Project checks — not run
No test suite, linter, or typecheck is configured anywhere in the project. This is
recorded in the requirements doc as the single largest debt.

## Review — not run
No diff to review. Nothing in the working tree was modified by this workflow beyond the
two artifacts in this directory.

## Verdict — Requirements delivered
The document is a description of the system as built, not an approved spec. Its accuracy
on intent (as opposed to behavior) is unverified — items marked **[observed]** and the 8
open questions are the places where the code does not reveal whether the behavior is
deliberate. Those need the repo owner's answer before any of it is treated as normative.
