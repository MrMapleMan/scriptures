# Requirements: Scriptures — annotation search & study toolkit

> **Reverse-engineered specification.** Derived by reading the code at commit `96a6017`
> (branch `sql`), not from an authored spec. It states what the system does *today* and
> flags what the code leaves undecided. Where behavior is only implied by an
> implementation detail rather than an evident intent, it is marked **[observed]** —
> those are candidates for "this is a bug, not a requirement." Open questions at the end
> are the ones worth answering before further work.

## Overview

A personal toolkit for searching and studying Latter-day Saint scripture alongside the
user's own Gospel Library annotations (highlights, notes, journal entries, tags). It has
two halves that share source data but not code:

1. **The PWA** (`webapp/`) — the delivered product. A build script merges the scripture
   text and an annotation export into a single SQLite file; a static, installable,
   offline browser app loads that file with sql.js and does all search and filtering
   in memory.
2. **The Python toolkit** (`scriptures/`, `notes/`, `analysis/`, notebook) — exploratory
   scripts and small libraries for loading verses into pandas, parsing the older CSV
   notes export, tag frequency/co-occurrence analysis, and ad-hoc annotation statistics.

The PWA is the mature, documented part. The Python half is a working sketchbook: it is
the origin of the ideas the PWA implements, and much of it is now superseded, personal,
or unrunnable as committed.

## Actors / users

- **The study user (primary, and effectively the only one).** Reads and searches their
  own annotations on a phone or laptop, online or offline. Never sees a terminal.
- **The maintainer (the repo owner, same person).** Exports annotations from Gospel
  Library, runs the build script, serves or deploys the app, and writes ad-hoc analysis
  scripts against the data.
- **No multi-user, no accounts, no server-side component.** Data is one person's, and
  the app is a static bundle.

## Data sources

- **`scripture_text.db`** — SQLite, a `verses` table with the full standard works
  (`volume_lds_url`, `volume_title`, `book_lds_url`, `book_title`, `book_long_title`,
  `chapter_number`, `verse_number`, `scripture_text`). Gitignored (`*.db`); derived from
  `scriptures/lds-scriptures.csv`, which *is* committed.
- **`resources/annotations/scripture_annotations_*.sqlite`** — a Gospel Library
  annotation export, table `AnnotationStorage`. Gitignored. Dated by export
  (`…_20260802.sqlite`).
- **`notes/LDSNotesDownload.csv`** — an older, CSV-shaped notes export used only by the
  Python half. Gitignored. Superseded by the SQLite export.

---

## Functional requirements

### A. Dataset build (`webapp/build_data.py`)

1. The build accepts `--verses` (scripture DB), `--annotations` (Gospel Library export),
   and `--out` (destination), and exits non-zero with a `not found: <path>` message if
   either input path does not exist.
2. Both source databases are opened **read-only** (`mode=ro`); the build must never
   modify an input.
3. An existing output file is deleted and rebuilt from scratch; the build is idempotent —
   running it twice on the same inputs yields equivalent databases.
4. The output schema is normalized into: `volumes`, `books`, `verses`, `annotations`,
   `annotation_tags`, `tags`, `highlights`, `meta`, with the indexes declared in `SCHEMA`.
5. Volumes are ordered by the canonical sequence `ot, nt, bofm, dc-testament, pgp`; any
   volume outside that list sorts last (`sort = 99`). Books preserve source row order.
6. An annotation URI of the form `/scriptures/<volume>/<book>/<chapter>` identifies the
   chapter. A highlight URI adds a paragraph suffix — `/scriptures/bofm/alma/27.p4` —
   and the `p` number is the **verse** number.
7. **Highlight offsets are 1-based inclusive *word* indexes into the paragraph as Gospel
   Library renders it, and word 1 is the printed verse number.** A verse-text word index
   is therefore `offset - 1`. `-1` (or missing) means "run to the start / end of the
   verse."
   - This convention is not arbitrary: scored against the 665 fully bounded highlights,
     it lands a clause boundary at 38.7% of interior starts and 62.1% of interior ends,
     versus 8.9% / 12.3% for reading offsets directly and ~13% / ~19% for random spans.
     It also explains the 89 highlights whose end offset is exactly `word_count + 1`.
   - Any change to this convention must be re-justified against that same scoring, not
     changed on intuition.
8. Both highlight bounds are clamped into `[1, word_count]`, and a reversed pair
   (`end < start`) is swapped rather than dropped. ~1.1% of highlights still land a word
   off at one end, because the export's tokenization differs from whitespace splitting
   (em dashes, KJV italics) — this is accepted, not a defect to chase.
9. A highlight targeting a verse absent from the scripture DB is skipped silently.
10. **Retention rule.** An annotation is kept as `kind = 'scripture'` if its chapter URI
    resolves to a known book *and* at least one highlight resolves to a known verse.
    Otherwise it is kept as `kind = 'note'` if it carries a note title or note body.
    Otherwise it is dropped and counted.
    - Consequence: annotations on general conference, manuals, Ensign, church history,
      JST, Bible Dictionary, Guide to the Scriptures, Official Declarations, and the
      proclamations survive **only if they carry a note**, since none of that text is in
      `scripture_text.db`.
    - Consequence: a chapter-level annotation whose only highlight targets a chapter
      heading or study summary demotes to `note`, and is dropped if it has no note.
11. **Tag names are read from the `Content` JSON blob's `Tags` array and nowhere else.**
    `TagsIds` is not a reliable parallel array (140 rows disagree on length) and is
    ignored. Tag names are deduplicated per annotation, preserving first-seen order.
12. `annotations.tags` is a comma-joined string for **display only**. Because 322 tag
    names themselves contain `", "`, it cannot be split back apart — readers must use
    `annotation_tags` (one row per tag).
13. Note HTML is stripped to plain text in `note_text`: `<br>` and closing block tags
    become newlines, `<li>` becomes `• `, the five standard entities plus `&nbsp;` are
    decoded, runs of horizontal whitespace collapse to one space, 3+ newlines collapse to
    two, and every line is trimmed. `note_html` retains the original.
14. `sort_date` is `Timestamp`, falling back to `Created`, falling back to `""`.
15. The build prints book/verse counts, kept/dropped annotation counts, highlighted-verse
    and distinct-tag counts, and the output size; it records
    `built_from_annotations`, `annotation_count`, `dropped_count`, and `tag_count` into
    `meta`, then `VACUUM`s.
16. **Reference figures** (2026-08-02 export): 5,721 scripture annotations + 747 notes
    kept, 3,005 dropped, 1,994 distinct tags, 9,162 of 9,164 highlight URIs parsing.
    A build that departs sharply from these is a signal the export format changed.

### B. Serving (`webapp/serve.sh`)

17. `serve.sh` builds `app/data/app.sqlite` if and only if it is missing, then serves
    `app/` over `python3 -m http.server` on `$PORT` (default 8000).
18. Input paths are overridable by the `VERSES` and `ANNOTATIONS` environment variables.
19. The app must remain deployable to any static host — no server-side logic may be
    introduced.

### C. The app: loading

20. On boot the app fetches `data/app.sqlite`, opens it with sql.js, and loads volumes,
    books, highlights, the text of every highlighted verse, all tag names, per-annotation
    tags, and all annotations into memory.
21. A failed load renders `Failed to load: <message>` in the status line, HTML-escaped,
    and logs the error. The app must not crash to a blank page.
22. Every string interpolated into rendered HTML is escaped (`escapeHtml`) — annotation
    text, tag names, book titles, error messages.

### D. The app: search

23. The search box matches plain text by default. **Regex** treats the term as a
    JavaScript regular expression; **Aa** makes it case-sensitive. Both options apply only
    to a search term, so they are visibly dimmed until one is typed.
24. An invalid regex shows an inline `Invalid regex: <reason>` and suppresses filtering
    rather than throwing; the previous result set is not silently reused as if valid.
25. Matches are highlighted in the rendered results, in both note text and verse text.
26. **Show — All / Notes / Scripture does double duty**: it filters the list *and* selects
    which text a search term is matched against — note text under Notes, verse text under
    Scripture, either under All.
27. Search input is debounced at 160 ms.

### E. The app: filtering

28. Results can be narrowed by volume, by book, and by "Note only" (entries not tied to a
    verse). Changing the volume re-populates the book list and clears a book selection
    that is no longer valid.
29. A filter-count badge shows the number of active filters: chosen tags + volume + book +
    note-only + tag regex.
30. Results sort by most recent, oldest, or scripture order (book sort → chapter → verse,
    with annotations having no reference sorting last).
31. **Tag selection and the tag regex are two constraints combined by one `all`/`any`
    toggle.** `all` ANDs them (and ANDs the chosen tags among themselves); `any` ORs
    them. A constraint that is not set does not participate.
32. **The tag chooser follows the results.** In `all` mode it offers only tags present on
    the current results, so no chip can lead to zero results. In `any` mode it widens past
    the current results, because an unrelated tag would otherwise be unreachable.
33. Selected tags remain listed even at a count of zero, so they can always be switched
    off.
34. The tag-search box narrows *which chips are listed* and has no effect on results —
    unlike the tag regex, which constrains results. The two must remain visually and
    behaviorally distinct.
35. The tag regex matches tag **names** case-insensitively; a result is kept if it carries
    at least one matching tag. Every currently matching tag is outlined in the chip list.
36. Tags shown on a result card are clickable and toggle that tag's selection.
37. The chip list renders at most 300 tags, followed by a `+N more — keep typing` marker.
38. The status line reports the result count, the total when filtered, and how many
    results carry notes.

### F. The app: reading

39. Results paginate 40 at a time behind a "Show N more (M left)" button.
40. Clicking a scripture reference opens the full chapter with every highlight in the
    chapter rendered in place; the verses belonging to the clicked annotation are tinted
    and scrolled into view.
41. Scripture highlights and search matches are layered per character over the same text,
    so an overlapping pair renders both.
42. `/` focuses the search box; `Esc` closes the reader; clicking the overlay backdrop
    closes the reader. While the reader is open, body scrolling is locked.
43. Any click outside the header dismisses the filter panel.

### G. The app: offline

44. The service worker precaches the shell, icons, sql.js vendor files, and
    `data/app.sqlite`, and the app must be fully usable offline once installed.
45. The shell (`.html` / `.css` / `.js` and navigations) is **network-first, cache
    fallback**, so an edit is visible without bumping the cache name. The dataset and
    other large immutable assets are **cache-first**.
46. Only same-origin `GET` requests are handled; everything else passes through.
47. Activating a new cache version deletes every older cache and claims open clients.
48. **The `CACHE` constant must be bumped whenever `app.sqlite` is rebuilt** — otherwise
    installed clients keep serving stale data indefinitely. This is currently a manual
    step with nothing enforcing it (see Open questions).
49. The app is installable: a web manifest supplies name, standalone display, theme
    colors, and 192/512 maskable icons.

### H. The Python toolkit

50. `Scriptures` loads the verse corpus into a pandas DataFrame, preferring
    `scriptures/scriptures.pkl` and falling back to fetching `lds-scriptures.csv` from
    GitHub raw when the pickle is absent. `scriptures_to_pickle.py` regenerates the pickle.
51. `Notes` loads a notes export (`.pkl` or `.csv`), splits the `tags` column on `"; "`,
    and offers: tag inventory and counts, alphabetical and by-count orderings, tag lookup
    by regex, notes-by-tag search (literal or regex, with flags), full-text search over
    note contents, and co-occurring tag counts for a given tag.
52. `analysis/annotations_analysis.py` opens an annotation export, adds a `Tags` column
    derived from `Content` if absent, loads it into a DataFrame, and reports
    annotation counts per book/location and books with no annotations.
53. `analysis/` also holds one-off conversion utilities: CSV → SQLite, CSV → a `.sql`
    script, and a random-tag generator for test fixtures.

---

## Edge cases & error states

| Case | Defined behavior |
|---|---|
| Input DB missing at build | Exit non-zero with `not found: <path>`. |
| Highlight URI unparseable | Skipped; annotation may still qualify via other highlights or its note. |
| Highlight verse not in scripture DB | That highlight is skipped silently. |
| Chapter known but no highlight resolves | Demoted to `note`; dropped if no note. |
| `OffsetStart`/`OffsetEnd` = `-1` or missing | Run to start / end of verse. |
| Offsets out of range | Clamped to `[1, word_count]`. |
| `end < start` | Swapped. |
| Highlight with no `Color` | Defaults to `yellow`. |
| Malformed JSON in `Content` / `Highlights` | `load_json` returns the default; the annotation is processed without tags/highlights rather than failing the build. |
| Tag name containing `", "` | Correct via `annotation_tags`; the joined `annotations.tags` string is display-only and unparseable. **[observed]** |
| Invalid search regex | Inline error, filtering suppressed. |
| Invalid tag regex | Inline error, tag constraint dropped. |
| Zero-length regex match | Advanced by one character to avoid an infinite loop; capped at 500 ranges per text. |
| No tags in the current results | `No tags in these results` / `No matching tags in these results`. |
| Volume changed with an incompatible book selected | Book selection cleared. |
| `app.sqlite` fetch fails | `Failed to load: …` in the status line. |
| Offline, first ever visit | App does not work — the service worker has not installed. Offline is only guaranteed after one successful online load. |
| `app.sqlite` rebuilt, `CACHE` not bumped | Installed clients keep the old dataset. Not currently detected. **[observed]** |
| `notes_with_content_df.pkl` missing | `Notes` falls back to CSV; `search_tags.py`'s path join is malformed and always falls through to CSV. **[observed]** |

---

## Non-functional requirements

54. **Fully client-side.** No network access at runtime beyond fetching the app's own
    static assets; no telemetry; annotation content never leaves the device.
55. **Dataset size** is roughly 18 MB and must stay small enough to precache and hold in
    memory on a phone. All filtering runs in memory over ~6,500 annotations and must feel
    immediate; search is debounced rather than indexed.
56. **Privacy.** The annotation export and the notes CSV are personal religious content
    and are gitignored. They must not be committed, and the app must not transmit them.
57. **No build toolchain.** Plain HTML/CSS/JS with a vendored sql.js — no bundler, no npm
    install, no framework. Deployment is copying `app/`.
58. **Light and dark themes** both supported.
59. **Accessibility.** Interactive controls carry ARIA labels/state; the reader is a
    labeled modal dialog; keyboard shortcuts are provided for search and dismissal.

---

## Out of scope

- Multi-user support, accounts, authentication, sync, or any server component.
- Editing, creating, or deleting annotations. The app is **read-only** over an export.
- Live integration with Gospel Library. Refreshing data means exporting by hand and
  re-running the build.
- Annotating or displaying non-scripture content (conference talks, manuals) beyond
  retaining its notes as searchable text.
- Full-text indexing (FTS5), fuzzy search, or ranked relevance — matching is linear and
  literal/regex only.
- The Python toolkit as a supported product. It is exploratory; it has no tests, no
  packaging, and no stability guarantee.
- `tmp/g3logPython/` — an unrelated third-party clone that is not part of this project.

---

## Known defects & debts (present in the code as scanned)

These are *not* requirements; they are the gaps a reader of this spec should know exist.

- **No automated tests anywhere in the project.** Every requirement above is currently
  verified by hand. The highlight-offset convention (#7) in particular is a numeric
  invariant with a documented scoring justification and no test guarding it.
- **`requirements.txt` is UTF-16 encoded** and will not install with `pip install -r`
  on a normal UTF-8 assumption.
- **Hardcoded personal absolute paths** in `sandbox.py`
  (`C:\Users\henri\…`), `analysis/annotations_analysis.py` (`C:/Users/henri/…`),
  `notes/read_notes_script.py` (`~/Documents/Church_of_Jesus_Christ/`), and
  `resources/annotations/start_note_search_app.sh` (`/mnt/c/Users/…`). None run on a
  fresh clone.
- **`notes/read_notes_script.py` executes work at import time** — it reads a CSV, fetches
  web pages, and writes a pickle as a side effect of being imported, with `sys.exit()`
  calls inside helper functions.
- **`analysis/scripture_db_sql.py` builds SQL by string concatenation** and stops after
  500 rows (`break`), so `create_scriptures_db.sql` is a truncated fixture, not a
  complete database script.
- **`analysis/*.py` use relative paths** (`scriptures.db`, `volume_book_info.csv`) that
  only resolve from specific working directories, unlike `webapp/build_data.py` which
  resolves paths relative to its own file.
- **`app.js` interpolates numbers into SQL** in `openReader` rather than binding them.
  The values are internal integers from the app's own state, so this is not currently
  reachable by user input — but it is one refactor away from being a real injection.
- **`resources/annotations/start_note_search_app.sh` is stale**: it references
  `build_dataset.py` and `app/data.sqlite`, neither of which matches the current
  `build_data.py` / `app/data/app.sqlite`, and its `unzip -d --force` argument order is
  wrong.
- **`Notes.flatten` is defined twice** and `readnotes.py` carries a TODO that
  `use_regex` in `isContained` is broken.
- **Duplicated logic** between `notes/read_notes_script.py`, `notes/search_tags.py`, and
  `notes/readnotes.py` (three implementations of tag flattening / related-tag counting).
- **Committed build outputs and generated artifacts** sit in the repo root
  (`results-*.csv`, `temp.csv`, `scriptures.pkl`, `myapp.log`, `.DS_Store`), several of
  them gitignored but present, and three separate virtualenvs are checked into the
  working tree.

---

## Open questions

1. **Is the Python half still alive?** Everything the PWA needs is in `webapp/`. Is
   `notes/` + `analysis/` (a) actively used for exploration, (b) worth salvaging into a
   supported library, or (c) ready to be archived? The answer determines whether the
   defects above are worth fixing at all.
2. **Should the cache bump be automated?** #48 is a manual step whose omission silently
   ships stale data to installed clients. Should `build_data.py` write a build hash the
   service worker or app compares, replacing the hand-edited `CACHE` constant?
3. **What is the intended answer for annotations on non-scripture content?** Today a
   conference-talk highlight with no note is dropped entirely (#10). Is losing it correct,
   or should those be retained as bare references so the export stays lossless?
4. **Is the 1.1% highlight misalignment acceptable indefinitely?** The README treats it as
   accepted. If not, the fix is matching Gospel Library's tokenizer, which is a
   substantially larger piece of work.
5. **What is the test strategy?** Given zero tests, the highest-value first targets look
   like `parse_highlights` offset handling, `strip_html`, and the retention rule in
   `build_annotations` — all pure functions over small fixtures. Is adding them in scope?
6. **Is `scripture_text.db` reproducible from what's committed?** `lds-scriptures.csv` is
   in the repo and the `.db` is gitignored, but the script that produces the exact schema
   `build_data.py` expects (`volume_lds_url`, `book_lds_url`, …) isn't obvious —
   `analysis/convert_scriptures_to_db.py` writes a different shape. A fresh clone may not
   be able to build the dataset.
7. **Is the repo intended to stay private?** The retention and privacy requirements (#56)
   assume yes. If it is ever public, the gitignored personal exports and the several
   hardcoded home paths need a deliberate pass.
8. **Multi-device use?** "Offline PWA" implies a phone, but the build runs on a desktop.
   Is there an intended deployment target (a static host, a LAN address), or is
   `serve.sh` on localhost the whole story?
