# Requirements: non-scripture annotation content

Derived from [`plan.md`](plan.md) (decisions settled 2026-08-07) and reviewed for gaps,
ambiguity, and testability. Where the plan left something under-specified, this document
states a concrete, testable rule and marks it **[gap-filled]** so it can be challenged.
Genuinely undecided items are in **Open questions** and must not be silently resolved.

## Overview

The dataset build drops 3,005 of 9,473 annotations because retention is coupled to whether
the referenced text is bundled locally. This work decouples the two: every annotation with a
note, a resolvable verse, or a URI is retained; non-scripture content is fetched on demand
from the Gospel Library content API, cached durably, and rendered with highlights in place.
It also adds content-type filtering, which the app has never had.

## Actors / users

- **The study user** — searches and reads their own annotations, online and offline, on
  phone and desktop. Never sees a terminal.
- **The maintainer** (same person) — exports annotations, runs `build_data.py`, serves or
  deploys `app/`.
- No accounts, no multi-user, no server-side state. The `serve.sh` write-back endpoint is a
  development-time convenience, not a server component of the product.

---

## Functional requirements

### A. Retention and classification (build)

1. `HIGHLIGHT_URI` must match `<uri>.<anchor>` for **any** URI namespace, not only
   `/scriptures/`. **[amended, cycle 1]** The anchor is *not* always `p<N>`: real
   annotations target `title29`, `aside2_p1`, `figure1_p29`, `study_summary1`, `kicker1`,
   and the opaque ids (`p_iilzI`) used in talks from 2025 on — 574 of 14,225 highlight
   entries, every one carrying a `Pid`. An anchor must therefore be `[A-Za-z][\w-]*`.
   It must start with a letter so a handbook section number (`/handbook/…/8.1`) is not
   mistaken for one. `CHAPTER_URI` remains scripture-specific, and only the `p<N>` shape
   names a verse.
2. An annotation is classified as exactly one `kind`:
   - `scripture` — chapter URI resolves to a bundled book **and** ≥1 highlight resolves to a
     known verse (unchanged from today);
   - `document` — not scripture, but has a URI, **except** a URI whose content-type bucket
     is *My Notes* (`/journal`), which names the notebook rather than a readable page.
     **[amended, cycle 1]** An earlier draft required a paragraph-suffixed highlight; that
     would drop bare `reference` bookmarks, which the edge-case table requires be retained
     as metadata-only cards. The `/journal` carve-out is what that clause was really
     reaching for.
   - `note` — no resolvable source, or a *My Notes* URI, and carries a note title or body.
3. An annotation is dropped **only** when it has no note, no resolvable verse, and no URI.
   Against the 2026-08-02 export this must drop **exactly 6 of 9,473** rows.
4. **[amended, cycle 1]** Kind counts against that export must be: `scripture` **5,721**;
   `document` **3,132**; `note` **614**. The original figures (~2,999 / ~753) were an
   estimate that counted only the *dropped* rows carrying a URI and overlooked the ~135
   previously-kept `note` rows that also carry one; under R2 those are documents, which is
   what makes their content fetchable. Totals reconcile exactly: 5,721 + 3,132 + 614 + 6 =
   9,473. A build departing from the amended figures by more than 1% is a regression.
5. Content type is derived **from the URI first**: the URI root selects the bucket; `/manual`
   and `/handbook` are refined by slug pattern; `CategoryName` is consulted **only** when no
   pattern matches. `raw_category` stores `CategoryName` verbatim.
6. An unrecognised URI root or slug must classify as **Other** — never dropped, never
   uncategorised.
7. The 136 null-`CategoryName` rows carrying a URI must classify per plan §4's table
   (Come Follow Me 54, Books & Lessons 43+3+2+1, Handbooks & Callings 18+5+1,
   Other 3, My Notes 1, Scriptures 1). **[amended, cycle 1]** This originally routed
   `/manual/for-the-strength-of-youth` to a `Youth` bucket that R8's list does not contain.
   R8 is authoritative: `/manual/for-the-strength-of-youth` is **Books & Lessons** (a
   booklet; the separate `/ftsoy` magazine root remains Magazines), and the `Youth`,
   `Life Help`, and `Archived Content` category names all fall to **Other**.
   The 618 URI-less journal rows classify as **My Notes**.
8. Buckets are: Scriptures, General Conference, My Notes, Magazines, Books & Lessons, Church
   History, Come Follow Me, Handbooks & Callings, Videos & Images, Topics, Music, Other.

### B. Content store (build)

9. New tables `documents` and `paragraphs` per plan §2, plus `doc_uri`/`para_id`/`pid`
   columns on `highlights` and `doc_uri` on `annotations`. Existing scripture tables and
   columns must not change shape.
10. **`build_data.py` must never make a network request.** A test must assert this by
    running a build with outbound sockets disabled.
11. The build reads `webapp/.cache/documents/` and embeds any paragraphs found there.
    Documents absent from the cache are written `fetch_state='unfetched'` and their
    annotations are retained regardless.
12. Cache files are keyed by `sha256(uri)` **[gap-filled]** — the plan said `<sha>` without
    saying of what. Each file stores `{uri, fetched_at, canonical_url, restricted,
    paragraphs: [{para_id, pid, sort, text}]}`.
13. A cache file that is malformed JSON, has a `uri` mismatching its filename hash, or fails
    schema validation must be **skipped with a warning**, leaving that document `'unfetched'`.
    It must not abort the build. **[gap-filled]**
14. `paragraphs.sort` is the paragraph's index in the source document's DOM order, preserved
    from the fetch. It is **not** derived from the numeric part of `para_id`, because ids are
    non-contiguous and non-monotonic.
15. **[amended, cycle 4]** Paragraph storage is namespace-dependent:
    - **General Conference** (`doc_uri` starting `/general-conference/`) stores **every
      paragraph of the talk**, not only the referenced ones, so the reader can show
      surrounding context.
    - **Every other namespace** stores only paragraphs referenced by at least one
      annotation, unchanged.

    Measured against the 2026-08-02 export and the local corpus: whole-talk is 16,017
    paragraphs / 4.83 MB across 460 annotated talks, against 2,069 / 0.66 MB
    referenced-only — a 7.3× increase, 34.8 paragraphs per talk against 4.5. The split
    exists because talks are short and bounded and their full text is already available
    locally from `conference_talks.db`, whereas the other 672 documents are handbook and
    manual chapters that are far longer; applying this rule to them was estimated at
    +15–20 MB and is explicitly **not** approved.
15a. **[added, cycle 4]** "Every paragraph" is bounded by what carries a resolvable
    `para_id`, and the two cache sources differ in what they can supply:
    - `source: "fetched"` — the live page is present, so every extracted paragraph
      (R17's `<p>`/`<h1>`–`<h6>` with an `[A-Za-z][\w-]*` id) is stored.
    - `source: "archive"` — corpus paragraphs carry no ids of their own; only paragraphs
      the R37 alignment map resolved have one. Storing an unmapped corpus paragraph is
      forbidden, because it could only be given a guessed id. An archive talk therefore
      stores every **mapped** paragraph, which is a superset of the referenced ones and
      may be a subset of the talk.

    A test must assert that a GC cache document with 20 paragraphs and 1 annotation
    embeds all 20, while a non-GC document in the same build embeds only the referenced
    ones — the namespace split is the thing at risk of being implemented as a global
    change.
16. `fetch_state` is one of `cached`, `empty`, `failed`, `unfetched`. A document with 0
    extractable paragraphs is `empty`, not `failed`.

### C. Paragraph extraction and anchoring

17. Paragraph extraction must match `id="pN"` on `<p>` **and** `<h1>`–`<h6>`. Matching only
    `<p>` silently drops heading anchors and is a defect.
18. A highlight resolves to a paragraph by **`Pid` (`data-aid`) first, falling back to
    `para_id`**. A `Pid` that matches must win even if `para_id` also matches a different row.
19. All cross-source text comparison must normalise via `html.unescape()` →
    `unicodedata.normalize('NFC', …)` → collapse whitespace runs → strip. This must live in
    one shared helper used by every caller, including the scripture path.
    **[clarified, cycle 1]** Unconditionally — there is no "looks like it has no markup"
    shortcut. Text that skips normalisation compares unequal against the same paragraph
    read from another source, and changes the word count highlight spans are clamped to.
20. Word offsets: `-1`/absent means run to the start/end of the paragraph; bounds are clamped
    into `[1, word_count]`; a reversed pair is swapped. Identical to the scripture rule
    except for the shift, which is R21.
21. The non-scripture offset shift must be **measured, not assumed**: score shift=0 against
    shift=−1 over the 1,275 bounded non-scripture highlights using the same clause-boundary
    method that produced the README's 38.7%/62.1% scripture table, and adopt the winner. The
    result and its table must be recorded in the README. Until measured, non-scripture
    partial-paragraph rendering must not ship.

### D. Rendering — cards and reader

22. A `document` card renders from metadata alone: title (`Location`), subtitle
    (`SubLocation`), item title (`ItemTitle`), category, date, tags, note. It must render
    fully when `fetch_state != 'cached'`.
23. **No annotation is ever hidden because its content is unavailable.**
24. **[amended, cycle 4 — resolves Open question 5 as (b)]** A `document` reader renders
    in `sort` order with highlights in place, and what it renders depends on the namespace,
    matching R15's storage split:
    - **General Conference** — the **whole talk**, when the whole talk is stored.
      Paragraphs tied to the open annotation are visually emphasised and the first of them
      is scrolled into view; the remainder render as unemphasised context. The emphasis
      must be distinguishable from a highlight — a highlight marks the words the user
      selected, emphasis marks which paragraph is the annotation's, and conflating them
      would misrepresent what was annotated.
    - **Every other namespace** — only the paragraphs tied to that annotation, unchanged.

    This is deliberately the same shape as R25's scripture reader (whole chapter, focused
    verses emphasised and scrolled to), and must reuse that mechanism rather than
    introducing a second one.
24c. **[added, cycle 4]** When the whole talk renders, it shows **every highlight on that
    document, from every annotation** — not only those of the annotation the reader was
    opened from. Emphasis stays tied to the opened annotation, so the two are independent:
    a paragraph may be highlighted without being focused. 260 of 461 annotated talks carry
    more than one annotation and one carries 15, so the narrower reading hides most of the
    user's own marks on the page in front of them. This is not a new idea — R25's chapter
    reader has always rendered every highlight in the chapter — so it is a defect being
    corrected, not a feature being added. Namespaces that render annotation-only
    (R24's second clause) keep annotation-scoped highlights, since there is no surrounding
    document on screen for other marks to belong to.
24a. **[added, cycle 4]** Fallbacks, since "the whole talk" is not always available:
    - A GC document holding only referenced paragraphs (cached before R15, or an archive
      talk whose map covered only the anchors) renders exactly as it does today. Partial
      storage must never render as a talk with silent gaps — if the stored paragraphs are
      not contiguous in `sort`, the reader must not imply they are.
    - Context paragraphs are rendered from stored text only. The reader must **not** fetch
      additional content to fill a talk out.
    - Emphasis and scroll-to must still work when the annotation's anchors all miss, in
      which case the talk renders as context only, with R26's existing anchor-miss notice.
24b. **[added, cycle 4]** Rendering the whole talk changes the cost of a card, so the
    **card** (R22) is unaffected: it continues to show only annotated paragraphs. Only the
    reader expands. A test must assert a GC card does not grow to the whole talk.
25. A `scripture` reader keeps its current whole-chapter behaviour, unchanged.
26. Reader states and their required UI, per plan §3: `cached`, `not cached + online`,
    `fetch failed`, `offline + not cached`, `restricted`, `empty`, `partial anchor miss`.
    Every non-success state must offer the `canonical_url` outbound link; `failed` must also
    offer **Retry**.
27. All rendered text remains HTML-escaped (existing spec #22).

### E. Runtime fetch, cache, write-back

28. Runtime fetches go to
    `https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content?lang=eng&uri=<uri>`.
29. Fetched documents persist in **IndexedDB** as structured paragraph rows, rendered by the
    same code path as build-embedded paragraphs.
30. Concurrent opens of the same document must issue **one** network request (in-flight map).
31. When a document exists both build-embedded and in IndexedDB, **IndexedDB wins**, since it
    is never older than the build. **[gap-filled]**
32. The service worker must not precache `churchofjesuschrist.org`. It gets a runtime route
    scoped to that origin and API path only; all other cross-origin requests pass through.
33. **Idle background warming** (approved): when online, not on a metered connection, and the
    UI has been idle ≥ 30s **[gap-filled]**, fetch unvisited documents at ≤2 concurrent with
    ≥500 ms spacing **[gap-filled]**, until the cache is complete. Off by default behind a
    visible toggle whose state persists. It must pause on user interaction, on going offline,
    and on 3 consecutive failures **[gap-filled]**.
34. Write-back path 1 — `serve.sh` serves via a small `http.server` subclass accepting
    `POST /_cache/<sha256>`, writing to `webapp/.cache/documents/`. It must:
    bind `127.0.0.1` only; reject any path outside the documented one; cap body size at
    256 KB **[gap-filled]**; validate the payload against R12's schema; and **verify the
    payload `uri` is referenced by the current dataset**, rejecting anything else.
    **[amended, cycle 1]** Two additions the original wording did not force:
    (a) the allow-list must **fail closed** — an empty list (no dataset yet, or an
    `app.sqlite` predating the `documents` table) disables write-back entirely rather than
    disabling the check; (b) the endpoint must **reject cross-site requests**, because a
    POST with a simple content type is not preflighted, so any page the user is browsing
    could otherwise write into the cache while the dev server is running.
34a. **[added, cycle 1]** `canonical_url` from a cache document is rendered as an `href`
    and arrives from untrusted input, so it must be restricted to `http`/`https`; any other
    scheme is discarded. A `javascript:` URL there would execute in the app's origin.
35. The app posts newly fetched documents to that endpoint fire-and-forget; failure is
    ignored and never surfaces to the user (static hosts have no such endpoint).
36. Write-back path 2 — an in-app **Export fetched content** control downloads one JSON
    containing every IndexedDB document, in a form that can be unpacked into
    `webapp/.cache/documents/` **[gap-filled: a small `unpack_export.py` helper ships with
    it, since hand-splitting a combined JSON is not reasonable]**.

### F. Anchored offline fallback for General Conference (approved)

37. An offline alignment map may be built from `conference_talks.db` by aligning its
    paragraph sequence to fetched content with `difflib.SequenceMatcher`, mapping each real
    `para_id` to a DB paragraph index.
38. `p1`/`p2` must be synthesised from the DB's `speaker`/`calling` columns when the live
    markup numbers the byline and those columns match exactly.
39. Alignment is **verification-gated**: a document's map is stored only if every anchor the
    annotations need resolved. A partial map is discarded rather than stored. **[gap-filled]**
40. When a GC document is uncached and unreachable, the reader renders from the corpus using
    the stored map, with highlights placed, labelled as served from the local archive.
40a. **[added, cycle 4]** Every writer of a GC cache document must satisfy R15/R15a, not
    just `build_data.py`: `build_alignment.py` in both `--learn` and replay modes, the
    rejected-talk live-page fallback, and the app's runtime fetch. A tool that keeps
    filtering to the annotated anchors would leave R15 unmet for the 461 talks already
    cached, and re-running it must upgrade those documents in place rather than skipping
    them as already present.
41. `conference_talks.db` lives outside the repo at an absolute path. Its location must be a
    **configurable option defaulting to absent**, and every corpus feature must degrade to
    "unavailable" when it is missing. No build or test may require it. **[gap-filled]**

### G. Filter UI

42. Content-type checkboxes derived from data at load time with live counts — never
    hardcoded in HTML.
43. All-checked and none-checked both mean "no constraint".
44. Checkbox counts reflect all *other* active filters but not the content-type filter
    itself, mirroring the existing tag facet behaviour. **[gap-filled]**
45. Content-type counts toward the filter badge only when not all boxes are checked.
46. The **Show** control splits into *Search in:* `Notes` / `Content` / `Both` (search target
    only) and the content-type checkboxes (filter only).
47. Volume and Book selects disable when Scriptures is unchecked.
48. `/` focus, `Esc` close, and existing keyboard behaviour must not regress.

---

## Edge cases & error states

| Case | Required behaviour |
|---|---|
| Annotation with URI but no highlights (82 docs) | Retained as `document`; metadata-only card; reader shows "no paragraph content at this reference" + outbound link. |
| URI-less, note-less, verse-less row (6 rows) | Dropped, counted. |
| `Pid` present but not found in content | Fall back to `para_id`; if that also misses, render resolved paragraphs and note the rest unavailable. |
| Paragraph id on a heading | Extracted and rendered like any paragraph (R17). |
| Cache file corrupt / hash mismatch | Skipped with warning; document stays `unfetched`; build succeeds. |
| API returns 404 (e.g. retired Handbook 2) | `fetch_state='failed'`; annotations retained; reader shows failure + outbound link. |
| API returns `restricted: true` | Distinct message; no retry loop. |
| API returns 0 paragraphs | `empty`, not an error. |
| Malformed JSON from API | Treated as a fetch failure; must not throw uncaught. |
| Offline, uncached, GC doc with alignment map | Render from corpus (R40). |
| Offline, uncached, no map | "Not available offline" + outbound link. |
| Network returns mid-fetch to online | `online` event re-enables fetching and warming. |
| Two simultaneous opens of one doc | One request (R30). |
| Every content-type box unchecked | Treated as no constraint (R43), not empty results. |
| Volume selected, then Scriptures unchecked | Volume/Book disable; their filter contribution is ignored while disabled. |
| Corpus DB absent | All corpus features report unavailable; nothing else degrades (R41). |
| Export JSON re-imported twice | Idempotent — same content, no duplicate paragraph rows. |

## Non-functional requirements

49. Client-side only. Annotation content never leaves the device except as URI lookups
    against the Church's own API.
50. **[amended, cycle 4]** Dataset size. The ~20 MB figure was an estimate made before
    retention was corrected upward by ~3,000 annotations (R4) and before R15's whole-talk
    rule. Measured actuals: 22.0 MB at cycle 3, 23.3 MB once the 461 GC talks were cached
    referenced-only, and 29.9 MB measured under R15 — higher than the ~27.5 MB predicted,
    because that prediction counted text only and ignored row and index overhead across
    14,887 paragraph rows. **[amended again, cycle 4]** The budget is **40 MB**, raised by
    the owner from 30 MB once R15 and R40a together were measured against it; a build
    exceeding 40 MB is a regression to be investigated, not a silent acceptance. This
    resolves the R40a/R50 conflict in favour of completing R40a.
    Filtering stays in-memory and
    immediate over ~9,500 annotations, and the paragraph count rising from ~2,069 to
    ~16,017 must not regress filter or search responsiveness.
51. No build toolchain, no bundler, no npm dependency. Vendored sql.js only.
52. The write-back endpoint is a local-only development affordance and must be safe by
    construction (R34) — it writes files from HTTP input.
53. Tests use stdlib `unittest`; the project has no pytest. **No test may hit the live API or
    require `conference_talks.db`.**
54. Light/dark themes and existing accessibility behaviour must not regress.

## Out of scope

- Full-text search across all 4,378 conference talks (plan §6) — recorded, not built.
- An "Open full document" reader action for non-scripture content.
- Editing, creating, or syncing annotations. Still read-only over an export.
- Replacing the hand-edited service-worker `CACHE` constant (plan Phase 6) — unless pulled
  forward; see Open questions.
- Any change to how scripture verses are stored or rendered, beyond the shared normalisation
  helper (R19).

## Open questions

1. **`hear-him-launch` (3 rows)** — no category anywhere in the export; parked in **Other**.
   Confirm or assign.
2. **Phase 6 cache-versioning.** The plan lists it as a follow-on, but data now changes on
   every browse-and-rebuild cycle, so a stale service-worker cache becomes much more likely.
   Recommend pulling it forward into this work; not assumed.
3. **If R21's measurement is inconclusive** (the two conventions score within noise), which
   shift wins by default? Recommend shift=0 for non-scripture, since the verse-number
   rationale demonstrably does not apply — but this should be an explicit call.
5. **[raised, cycle 4 — the consequential one] R15 stores whole talks; R24 still renders
   only the annotated paragraphs. Storage alone is user-invisible.** The change was asked
   for as "preloading the whole talk *so that it can be displayed if the talk reader is
   opened*", which reads as intent to display — but R24 is a settled decision from an
   earlier round ("the reader should only display the paragraphs tied to the annotation"),
   and overriding a settled decision by inferring it from a sizing question would be
   exactly the silent resolution this review is supposed to prevent. Taken literally,
   R15 as amended costs ~4.2 MB and delivers no visible behaviour, because
   `refreshContentText` also indexes only resolved highlight paragraphs, so it does not
   even widen search.

   Three coherent readings, needing an explicit choice:
   - **(a) Storage only, as amended.** Honest to the stated scope; ships 4.2 MB of text
     nothing reads yet. Defensible only as groundwork.
   - **(b) Recommended — GC reader renders the full talk**, annotated paragraphs visually
     emphasised and scrolled to, the rest as context. This is what makes the 4.2 MB pay
     for itself, and it matches the wording of the request.
   - **(c) Storage plus search.** Include stored-but-unannotated paragraphs in
     `contentText` so full-talk text becomes searchable, without changing the reader.
     Cheaper than (b); note it changes what "Search in: Content" means and would surface
     matches on paragraphs the user never annotated.

   (b) and (c) are not exclusive.

   **ANSWERED, cycle 4: (b).** R24 is amended accordingly and this question is closed.
   (c) was **not** chosen and must not be implemented — `refreshContentText` keeps indexing
   only resolved highlight paragraphs, so "Search in: Content" continues to mean "text you
   annotated", not "text of talks you annotated". Widening it silently would be a
   behaviour change nobody asked for.
6. **Export/import format versioning** — should the export JSON carry a schema version so a
   future change can migrate old exports? Recommend yes; cheap now, impossible later.
