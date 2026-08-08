/* Scripture Notes -- offline annotation browser.
   Loads a prebuilt SQLite file with sql.js and does all filtering in memory.

   Scripture text is bundled. Non-scripture content (talks, manuals, magazines)
   is fetched from the Gospel Library content API the first time you open it,
   stored in IndexedDB, and posted back to the dev server so the next build
   embeds it. An annotation is never hidden because its content is missing --
   the card always renders from the metadata in the export. */

const DB_URL = "data/app.sqlite";
const PAGE_SIZE = 40;
const CONTENT_API =
  "https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content?lang=eng&uri=";
const CONTENT_ORIGIN = "https://www.churchofjesuschrist.org";
const IDB_NAME = "scripture-notes-content";
const IDB_STORE = "documents";
const EXPORT_VERSION = 1;
const WARM_IDLE_MS = 30000;
const WARM_SPACING_MS = 500;
const WARM_CONCURRENCY = 2;
const WARM_MAX_FAILURES = 3;

const state = {
  db: null,
  annotations: [],
  byId: new Map(),
  highlights: new Map(),   // annotation id -> [{verse, s, e, color, style}]
  docHighlights: new Map(),// annotation id -> [{docUri, paraId, pid, s, e, color, style}]
  // docUri -> every highlight on that document, from every annotation. The
  // reader shows the whole talk, so it shows everything marked in it -- the
  // chapter reader has always done this for verses.
  docHighlightsByDoc: new Map(),
  verseText: new Map(),    // "bookId:chapter:verse" -> text
  paragraphs: new Map(),   // "docUri\x1fparaId" -> {text, pid, sort}
  paragraphsByPid: new Map(), // "docUri\x1fpid" -> same record, for Pid-first lookup
  // docUri -> [record], every stored paragraph of that document in sort order.
  // The reader needs a document's paragraphs as a whole, which neither of the
  // key-per-paragraph maps above can answer without scanning all of them.
  paragraphsByDoc: new Map(),
  documents: new Map(),    // docUri -> {uri, category, title, subtitle, itemTitle, ...}
  books: new Map(),
  volumes: [],
  facetTags: [],
  facetTotal: 0,
  query: "",
  // Search target only. Type filtering lives in the category checkboxes.
  searchIn: "both",        // "both" | "notes" | "content"
  categories: new Set(),   // empty = no constraint
  allCategories: [],       // [{name, count}]
  regex: false,
  caseSensitive: false,
  volume: "",
  book: "",
  sort: "recent",
  tagMode: "all",
  tagSort: "count",
  chosenTags: new Set(),
  tagFilter: "",
  tagRegexSource: "",
  tagRegex: null,
  tagRegexHits: null,
  allTags: [],
  results: [],
  shown: 0,
  matcher: null,
  warming: false,
  warmFailures: 0,
  readerDoc: null,         // uri currently open in the document reader
};

const $ = (sel) => document.querySelector(sel);
const el = {
  status: $("#status"),
  results: $("#results"),
  more: $("#more"),
  q: $("#q"),
  qClear: $("#q-clear"),
  regexErr: $("#regex-err"),
  searchOpts: $(".search-opts"),
  searchFlags: $(".search-flags"),
  tagRegex: $("#tag-regex"),
  tagRegexHint: $("#tag-regex-hint"),
  tagRegexErr: $("#tag-regex-err"),
  filters: $("#filters"),
  filtersToggle: $("#filters-toggle"),
  filterCount: $("#filter-count"),
  volume: $("#f-volume"),
  book: $("#f-book"),
  volumeField: $("#f-volume-field"),
  bookField: $("#f-book-field"),
  sortSel: $("#f-sort"),
  types: $("#type-list"),
  typesAll: $("#types-all"),
  warmToggle: $("#warm-toggle"),
  warmStatus: $("#warm-status"),
  exportBtn: $("#export-content"),
  tagSearch: $("#tag-search"),
  tagList: $("#tag-list"),
  chosenTags: $("#chosen-tags"),
  tagsClear: $("#tags-clear"),
  tagModeToggle: $("#tag-mode-toggle"),
  tagModeHint: $("#tag-mode-hint"),
  reader: $("#reader"),
  readerTitle: $("#reader-title"),
  readerBody: $("#reader-body"),
  readerClose: $("#reader-close"),
};

/* ------------------------------------------------------------------ utils */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function rowsOf(db, sql) {
  const out = [];
  const stmt = db.prepare(sql);
  while (stmt.step()) out.push(stmt.getAsObject());
  stmt.free();
  return out;
}

function plural(n, word) {
  return n.toLocaleString() + " " + word + (n === 1 ? "" : "s");
}

function verseKey(bookId, chapter, verse) {
  return bookId + ":" + chapter + ":" + verse;
}

/* Joined with US (\x1f), which cannot appear in a URI or a DOM id, so a URI
   ending in a para id cannot collide with a shorter one. */
function paraKey(docUri, paraId) {
  return docUri + "\x1f" + paraId;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/* Word index (1-based, inclusive) -> character range in the text.
   Gospel Library stores highlight bounds as word offsets, not characters. */
function wordRangeToChars(text, wordStart, wordEnd) {
  const re = /\S+/g;
  let m, i = 0, start = -1, end = -1;
  while ((m = re.exec(text)) !== null) {
    i += 1;
    if (i === wordStart) start = m.index;
    if (i === wordEnd) end = m.index + m[0].length;
    if (end !== -1) break;
  }
  if (start === -1) return null;
  if (end === -1) end = text.length;
  return [start, end];
}

/* ------------------------------------------------------------------- idb */

/* Runtime-fetched content lives in IndexedDB as structured paragraph rows so
   it renders through exactly the same path as build-embedded paragraphs. */
function openIdb() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) { resolve(null); return; }
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) db.createObjectStore(IDB_STORE, { keyPath: "uri" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);   // storage disabled: degrade, do not fail
  });
}

function idbAll(db) {
  return new Promise((resolve) => {
    if (!db) { resolve([]); return; }
    const req = db.transaction(IDB_STORE, "readonly").objectStore(IDB_STORE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => resolve([]);
  });
}

function idbPut(db, doc) {
  return new Promise((resolve) => {
    if (!db) { resolve(false); return; }
    const tx = db.transaction(IDB_STORE, "readwrite");
    tx.objectStore(IDB_STORE).put(doc);
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => resolve(false);
  });
}

let idb = null;

/* ------------------------------------------------------------------ load */

function adoptParagraphs(doc) {
  /* IndexedDB replaces the build-embedded set rather than merging into it: it
     is never older, so a paragraph the newer revision dropped must go too
     instead of lingering with stale text. */
  const fresh = doc.paragraphs || [];
  const keep = new Set(fresh.map((p) => paraKey(doc.uri, p.para_id)));
  const prefix = paraKey(doc.uri, "");
  for (const key of [...state.paragraphs.keys()]) {
    if (key.startsWith(prefix) && !keep.has(key)) state.paragraphs.delete(key);
  }
  for (const key of [...state.paragraphsByPid.keys()]) {
    if (key.startsWith(prefix)) state.paragraphsByPid.delete(key);
  }
  const all = [];
  for (const p of fresh) {
    const record = { paraId: p.para_id, text: p.text, pid: p.pid || null, sort: p.sort || 0 };
    state.paragraphs.set(paraKey(doc.uri, p.para_id), record);
    if (p.pid) state.paragraphsByPid.set(paraKey(doc.uri, p.pid), record);
    all.push(record);
  }
  all.sort((a, b) => a.sort - b.sort);
  if (all.length) state.paragraphsByDoc.set(doc.uri, all);
  else state.paragraphsByDoc.delete(doc.uri);
  const known = state.documents.get(doc.uri);
  if (known) {
    known.fetchState = doc.error ? "failed" : (fresh.length ? "cached" : "empty");
    known.source = doc.source || "fetched";
    if (doc.canonical_url) known.canonicalUrl = doc.canonical_url;
    if (doc.restricted) known.restricted = true;
  }
}

async function load() {
  const SQL = await initSqlJs({ locateFile: (f) => "vendor/" + f });
  const res = await fetch(DB_URL);
  if (!res.ok) throw new Error("could not fetch " + DB_URL + " (" + res.status + ")");
  const db = new SQL.Database(new Uint8Array(await res.arrayBuffer()));
  state.db = db;

  state.volumes = rowsOf(db, "SELECT id, url, title FROM volumes ORDER BY sort, id");
  for (const b of rowsOf(db, "SELECT id, volume_id, url, title, sort FROM books ORDER BY sort")) {
    state.books.set(b.id, { id: b.id, volumeId: b.volume_id, url: b.url, title: b.title, sort: b.sort });
  }

  for (const d of rowsOf(db, `SELECT uri, category, title, subtitle, item_title, canonical_url,
                                     fetch_state, source, restricted FROM documents`)) {
    state.documents.set(d.uri, {
      uri: d.uri, category: d.category, title: d.title, subtitle: d.subtitle,
      itemTitle: d.item_title, canonicalUrl: d.canonical_url, fetchState: d.fetch_state,
      source: d.source || "fetched", restricted: Boolean(d.restricted),
    });
  }
  for (const p of rowsOf(db, "SELECT doc_uri, para_id, pid, sort, text FROM paragraphs")) {
    const record = { paraId: p.para_id, text: p.text, pid: p.pid, sort: p.sort };
    state.paragraphs.set(paraKey(p.doc_uri, p.para_id), record);
    if (p.pid) state.paragraphsByPid.set(paraKey(p.doc_uri, p.pid), record);
    let all = state.paragraphsByDoc.get(p.doc_uri);
    if (!all) state.paragraphsByDoc.set(p.doc_uri, (all = []));
    all.push(record);
  }
  for (const all of state.paragraphsByDoc.values()) all.sort((a, b) => a.sort - b.sort);

  for (const h of rowsOf(db, `SELECT annotation_id, book_id, chapter, verse, word_start, word_end,
                                     color, style FROM highlights WHERE book_id IS NOT NULL`)) {
    let list = state.highlights.get(h.annotation_id);
    if (!list) state.highlights.set(h.annotation_id, (list = []));
    list.push({ bookId: h.book_id, chapter: h.chapter, verse: h.verse,
                s: h.word_start, e: h.word_end, color: h.color, style: h.style });
  }
  for (const h of rowsOf(db, `SELECT annotation_id, doc_uri, para_id, pid, word_start, word_end,
                                     color, style FROM highlights WHERE doc_uri IS NOT NULL`)) {
    let byDoc = state.docHighlightsByDoc.get(h.doc_uri);
    if (!byDoc) state.docHighlightsByDoc.set(h.doc_uri, (byDoc = []));
    byDoc.push({ docUri: h.doc_uri, paraId: h.para_id, pid: h.pid,
                 s: h.word_start, e: h.word_end, color: h.color, style: h.style });
    let list = state.docHighlights.get(h.annotation_id);
    if (!list) state.docHighlights.set(h.annotation_id, (list = []));
    list.push({ docUri: h.doc_uri, paraId: h.para_id, pid: h.pid,
                s: h.word_start, e: h.word_end, color: h.color, style: h.style });
  }

  for (const v of rowsOf(db, `SELECT DISTINCT v.book_id, v.chapter, v.verse, v.text
                              FROM verses v JOIN highlights h
                                ON h.book_id = v.book_id AND h.chapter = v.chapter
                               AND h.verse = v.verse`)) {
    state.verseText.set(verseKey(v.book_id, v.chapter, v.verse), v.text);
  }

  state.allTags = rowsOf(db, "SELECT name FROM tags ORDER BY name").map((r) => r.name);

  // One row per tag: 322 tag names contain ", ", so the comma-joined
  // annotations.tags column cannot be split back apart safely.
  const tagsByAnnotation = new Map();
  for (const r of rowsOf(db, "SELECT annotation_id, tag FROM annotation_tags")) {
    let list = tagsByAnnotation.get(r.annotation_id);
    if (!list) tagsByAnnotation.set(r.annotation_id, (list = []));
    list.push(r.tag);
  }

  for (const a of rowsOf(db, `SELECT id, kind, category, type, location, subtitle, item_title,
                                     doc_uri, book_id, chapter, verse_start, verse_end,
                                     note_title, note_text, verse_text, refs_json,
                                     created, updated, sort_date
                              FROM annotations`)) {
    const book = a.book_id ? state.books.get(a.book_id) : null;
    const tags = tagsByAnnotation.get(a.id) || [];
    const ann = {
      id: a.id,
      kind: a.kind,
      category: a.category,
      type: a.type,
      location: a.location || a.note_title || "Note",
      subtitle: a.subtitle || "",
      itemTitle: a.item_title || "",
      docUri: a.doc_uri || null,
      bookId: a.book_id,
      book,
      volumeId: book ? book.volumeId : null,
      chapter: a.chapter,
      verseStart: a.verse_start,
      verseEnd: a.verse_end,
      noteTitle: a.note_title || "",
      noteText: a.note_text || "",
      verseText: a.verse_text || "",
      tags,
      tagSet: new Set(tags),
      refs: a.refs_json ? JSON.parse(a.refs_json) : null,
      created: a.created,
      updated: a.updated,
      sortDate: a.sort_date || "",
      noteBlob: ((a.note_title || "") + "\n" + (a.note_text || "")).trim(),
      hasNote: Boolean((a.note_title || "").trim() || (a.note_text || "").trim()),
    };
    ann.sortRef = book
      ? book.sort * 1e6 + (a.chapter || 0) * 1000 + (a.verse_start || 0)
      : Number.MAX_SAFE_INTEGER;
    state.annotations.push(ann);
    state.byId.set(ann.id, ann);
  }

  idb = await openIdb();
  for (const doc of await idbAll(idb)) adoptParagraphs(doc);

  refreshContentText();
  countCategories();

  const meta = {};
  for (const r of rowsOf(db, "SELECT key, value FROM meta")) meta[r.key] = r.value;
  return meta;
}

/* Searchable content text per annotation: verses for scripture, paragraph text
   for documents. Recomputed when new paragraphs arrive so freshly fetched
   content becomes searchable without a rebuild. */
function refreshContentText() {
  for (const ann of state.annotations) {
    if (ann.kind === "scripture") { ann.contentText = ann.verseText; continue; }
    if (ann.kind !== "document") { ann.contentText = ""; continue; }
    const parts = [];
    for (const h of state.docHighlights.get(ann.id) || []) {
      const para = resolveParagraph(h.docUri, h);
      if (para && !parts.includes(para.text)) parts.push(para.text);
    }
    ann.contentText = parts.join("\n");
  }
}

function countCategories() {
  const counts = new Map();
  for (const ann of state.annotations) counts.set(ann.category, (counts.get(ann.category) || 0) + 1);
  state.allCategories = [...counts].map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

/* --------------------------------------------------------------- matching */

function buildMatcher() {
  el.regexErr.hidden = true;
  const q = state.query.trim();
  if (!q) return (state.matcher = null);
  const flags = "g" + (state.caseSensitive ? "" : "i");
  const source = state.regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  try {
    state.matcher = new RegExp(source, flags);
  } catch (err) {
    state.matcher = null;
    el.regexErr.textContent = "Invalid regex: " + err.message.replace(/^.*?:\s*/, "");
    el.regexErr.hidden = false;
  }
  return state.matcher;
}

function buildTagRegex() {
  el.tagRegexErr.hidden = true;
  state.tagRegex = null;
  state.tagRegexHits = null;
  const source = state.tagRegexSource.trim();
  if (!source) return;
  let re;
  try {
    re = new RegExp(source, "i");
  } catch (err) {
    el.tagRegexErr.textContent = "Invalid regex: " + err.message.replace(/^.*?:\s*/, "");
    el.tagRegexErr.hidden = false;
    return;
  }
  state.tagRegex = re;
  state.tagRegexHits = new Set(state.allTags.filter((name) => re.test(name)));
}

function matchesTagConstraints(ann, tags, hits) {
  const narrowing = state.tagMode === "all";
  const chosenHit = tags.length
    ? (narrowing ? tags.every((t) => ann.tagSet.has(t)) : tags.some((t) => ann.tagSet.has(t)))
    : null;
  const regexHit = hits ? ann.tags.some((t) => hits.has(t)) : null;
  return narrowing
    ? chosenHit !== false && regexHit !== false
    : chosenHit === true || regexHit === true;
}

function testMatch(text) {
  if (!text) return false;
  state.matcher.lastIndex = 0;
  return state.matcher.test(text);
}

function annotationMatches(ann) {
  if (!state.matcher) return true;
  const notes = state.searchIn !== "content" && testMatch(ann.noteBlob);
  const content = state.searchIn !== "notes" && testMatch(ann.contentText);
  return Boolean(notes || content);
}

function matchRanges(text) {
  if (!state.matcher || !text) return [];
  const ranges = [];
  state.matcher.lastIndex = 0;
  let m;
  while ((m = state.matcher.exec(text)) !== null) {
    if (m[0].length === 0) { state.matcher.lastIndex += 1; continue; }
    ranges.push([m.index, m.index + m[0].length]);
    if (ranges.length > 500) break;
  }
  return ranges;
}

/* -------------------------------------------------------------- filtering */

/* All-checked and none-checked both mean "no constraint", so unticking every
   box can never leave the app showing nothing. */
function categoryActive() {
  return state.categories.size > 0 && state.categories.size < state.allCategories.length;
}

function scriptureEnabled() {
  return !categoryActive() || state.categories.has("Scriptures");
}

function applyFilters() {
  buildMatcher();
  buildTagRegex();
  const searchable = state.query.trim() !== "" && state.matcher !== null;
  el.searchOpts.classList.toggle("idle", !state.query.trim());
  el.searchFlags.title = state.query.trim() ? "" : "Applies once you type a search term";
  const tags = [...state.chosenTags];
  const byType = categoryActive();
  const useScripture = scriptureEnabled();

  // Everything except the tag filter. Also the facet source for OR mode, so
  // that picking one tag does not hide the others you might want to add.
  const base = state.annotations.filter((ann) => {
    if (byType && !state.categories.has(ann.category)) return false;
    // Volume/Book are scripture-only; while disabled they must not filter.
    if (useScripture && state.volume && String(ann.volumeId) !== state.volume) return false;
    if (useScripture && state.book && String(ann.bookId) !== state.book) return false;
    if (searchable && !annotationMatches(ann)) return false;
    return true;
  });

  const hits = state.tagRegexHits;
  state.results = (tags.length || hits)
    ? base.filter((ann) => matchesTagConstraints(ann, tags, hits))
    : base;

  countFacetTags(state.tagMode === "all" ? state.results : base);
  renderTags();
  renderCategories();

  const cmp = {
    recent: (a, b) => (b.sortDate || "").localeCompare(a.sortDate || ""),
    oldest: (a, b) => (a.sortDate || "").localeCompare(b.sortDate || ""),
    reference: (a, b) => a.sortRef - b.sortRef || (a.sortDate || "").localeCompare(b.sortDate || ""),
  }[state.sort];
  state.results.sort(cmp);

  state.shown = 0;
  el.results.innerHTML = "";
  renderStatus();
  renderMore();
}

function renderStatus() {
  const n = state.results.length;
  const total = state.annotations.length;
  const bits = [n.toLocaleString() + (n === 1 ? " annotation" : " annotations")];
  if (n !== total) bits.push("of " + total.toLocaleString());
  const withNotes = state.results.reduce((acc, a) => acc + (a.hasNote ? 1 : 0), 0);
  if (withNotes) bits.push(withNotes.toLocaleString() + " with notes");
  el.status.textContent = bits.join(" · ");
}

/* -------------------------------------------------------------- rendering */

/* Render one passage, layering source highlights and search matches.
   Both are char ranges over the same text, so they are merged per character. */
function renderPassage(text, highlights, showMatches) {
  const marks = new Array(text.length).fill(null);
  for (const h of highlights || []) {
    // Still no span: the paragraph text is not known, so there is nothing to
    // measure a range against. Compared against null rather than falsiness so a
    // legitimate word offset of 0 is not silently discarded.
    if (h.s == null || h.e == null) continue;
    const range = wordRangeToChars(text, h.s, h.e);
    if (!range) continue;
    for (let i = range[0]; i < range[1]; i++) marks[i] = h;
  }

  const hits = new Array(text.length).fill(false);
  if (showMatches && state.matcher && state.searchIn !== "notes") {
    for (const [s, e] of matchRanges(text)) {
      for (let i = s; i < e; i++) hits[i] = true;
    }
  }

  let html = "";
  let i = 0;
  while (i < text.length) {
    const mark = marks[i];
    const hit = hits[i];
    let j = i + 1;
    while (j < text.length && marks[j] === mark && hits[j] === hit) j++;
    let chunk = escapeHtml(text.slice(i, j));
    if (mark) {
      const cls = "hl hl-" + (mark.color || "yellow") + (mark.style === "red-underline" ? " underline" : "");
      chunk = '<mark class="' + cls + '">' + chunk + "</mark>";
    }
    if (hit) chunk = '<mark class="q">' + chunk + "</mark>";
    html += chunk;
    i = j;
  }
  return html;
}

function renderNote(ann) {
  if (!ann.hasNote) return "";
  let body = escapeHtml(ann.noteText);
  if (state.matcher && state.searchIn !== "content") {
    const ranges = matchRanges(ann.noteText);
    if (ranges.length) {
      let out = "", last = 0;
      for (const [s, e] of ranges) {
        out += escapeHtml(ann.noteText.slice(last, s)) +
               '<mark class="q">' + escapeHtml(ann.noteText.slice(s, e)) + "</mark>";
        last = e;
      }
      body = out + escapeHtml(ann.noteText.slice(last));
    }
  }
  const title = ann.noteTitle
    ? '<span class="note-title">' + escapeHtml(ann.noteTitle) + "</span>"
    : "";
  return '<div class="note">' + title + body + "</div>";
}

/* Resolve a highlight to its paragraph, Pid first.

   Pid (the page's data-aid) survives content revisions; paragraph numbering
   does not. Without this the common case breaks: most documents are unfetched
   at build time, so the highlight row carries the anchor the annotation was
   made against, and the freshly fetched page may have renumbered it. */
function resolveParagraph(docUri, h) {
  return (h.pid && state.paragraphsByPid.get(paraKey(docUri, h.pid)))
      || state.paragraphs.get(paraKey(docUri, h.paraId))
      || null;
}

/* Fill in the span for highlights whose paragraph text was not available at
   build time -- which is nearly all of them, since a document is normally
   unfetched when the dataset is built and only resolved once the page has been
   downloaded at runtime. Without this the highlight rows keep the null spans
   the build wrote and renderPassage skips them, so a fetched document renders
   as plain untinted text.

   The rule is the same one build_data.py applies when it does have the text:
   with DOCUMENT_OFFSET_SHIFT unmeasured, a document highlight tints the whole
   paragraph rather than guessing which words the stored offsets mean. */
function spanHighlights(hl, text) {
  if (!text) return hl;
  let words = -1;
  return hl.map((h) => {
    if (h.s != null && h.e != null) return h;
    if (words < 0) words = text.split(/\s+/).filter(Boolean).length;
    return words ? Object.assign({}, h, { s: 1, e: words }) : h;
  });
}

/* Paragraphs this annotation touches, in document order, with their highlights. */
function documentPassages(ann) {
  const groups = new Map();
  for (const h of state.docHighlights.get(ann.id) || []) {
    // Group by the paragraph actually resolved, so two anchors that turn out to
    // be the same renumbered paragraph do not render it twice.
    const para = resolveParagraph(ann.docUri, h);
    const key = para && para.pid ? "pid:" + para.pid : h.paraId;
    if (!groups.has(key)) groups.set(key, { paraId: h.paraId, para, hl: [] });
    groups.get(key).hl.push(h);
  }
  const out = [];
  for (const g of groups.values()) {
    out.push({
      paraId: g.paraId,
      sort: g.para ? g.para.sort : Number.MAX_SAFE_INTEGER,
      text: g.para ? g.para.text : null,
      // The resolved record itself, so the context reader can identify which of
      // a document's paragraphs are this annotation's without re-resolving.
      record: g.para,
      hl: g.para ? spanHighlights(g.hl, g.para.text) : g.hl,
    });
  }
  out.sort((a, b) => a.sort - b.sort || a.paraId.localeCompare(b.paraId));
  return out;
}

/* General Conference stores the whole talk, so its reader can show the
   annotation in context. Mirrors the scripture reader: the whole unit renders,
   the paragraphs this annotation touches get `.focus`, and the first is
   scrolled to.

   Returns null whenever context rendering would be a lie or a no-op:
   - a namespace that does not store whole documents;
   - a document holding nothing beyond the annotated paragraphs, which is what
     a pre-R15 cache entry or an archive talk whose map covered only the anchors
     looks like -- that renders exactly as it did before;
   - a stored set with gaps in `sort`, which is not a whole talk. Rendering it
     as one would silently imply the missing paragraphs do not exist. */
function documentContext(ann, passages) {
  if (!stateStoresWholeDocument(ann.docUri)) return null;
  const all = state.paragraphsByDoc.get(ann.docUri);
  if (!all || all.length <= passages.length) return null;
  for (let i = 1; i < all.length; i++) {
    if (all[i].sort !== all[i - 1].sort + 1) return null;
  }
  // Match on the resolved record, not on para_id: a renumbered page resolves
  // through Pid, and comparing ids would emphasise nothing.
  const focused = new Set();
  for (const p of passages) if (p.record) focused.add(p.record);

  // Every highlight on this talk, not only the annotation that opened it. The
  // whole talk is on screen, so hiding the rest of the user's own marks in it
  // would be strange -- and the chapter reader already shows every highlight in
  // the chapter, so this keeps the two readers consistent.
  const hlFor = new Map();
  for (const h of state.docHighlightsByDoc.get(ann.docUri) || []) {
    const record = resolveParagraph(ann.docUri, h);
    if (!record) continue;
    let list = hlFor.get(record);
    if (!list) hlFor.set(record, (list = []));
    list.push(h);
  }
  return all.map((record) => ({
    text: record.text,
    focus: focused.has(record),
    hl: spanHighlights(hlFor.get(record) || [], record.text),
  }));
}

/* The storage rule has one home in gospel_content.py; this is its runtime
   half. Kept as a named function so the two stay findable together. */
function stateStoresWholeDocument(uri) {
  return Boolean(uri) && uri.startsWith("/general-conference/");
}

function renderCard(ann) {
  const card = document.createElement("article");
  card.className = "card";

  const meta = [];
  if (ann.kind === "note") meta.push(ann.type === "journal" ? "Journal" : "Note");
  else meta.push(ann.category);
  const date = formatDate(ann.sortDate);
  if (date) meta.push(date);

  const openable = ann.kind === "scripture" || ann.kind === "document";
  const head = openable
    ? '<button class="ref-btn" data-open="' + escapeHtml(ann.id) + '">' +
        escapeHtml(ann.location) + "</button>"
    : '<span class="ref-btn" style="color:var(--text)">' +
        escapeHtml(ann.noteTitle || ann.location) + "</span>";

  let html = '<div class="card-head">' + head +
             '<span class="card-meta">' + escapeHtml(meta.join(" · ")) + "</span></div>";

  const byline = [ann.subtitle, ann.itemTitle].filter(Boolean).join(" · ");
  if (ann.kind === "document" && byline) {
    html += '<div class="byline">' + escapeHtml(byline) + "</div>";
  }

  if (ann.kind === "scripture") {
    const hl = state.highlights.get(ann.id) || [];
    const byVerse = new Map();
    for (const h of hl) {
      const key = verseKey(h.bookId, h.chapter, h.verse);
      if (!byVerse.has(key)) byVerse.set(key, []);
      byVerse.get(key).push(h);
    }
    const keys = [...byVerse.keys()].sort(
      (a, b) => Number(a.split(":")[2]) - Number(b.split(":")[2]));
    for (const key of keys) {
      const text = state.verseText.get(key);
      if (!text) continue;
      html += '<p class="verse"><span class="vn">' + key.split(":")[2] + "</span>" +
              renderPassage(text, byVerse.get(key), true) + "</p>";
    }
  } else if (ann.kind === "document") {
    const passages = documentPassages(ann);
    const withText = passages.filter((p) => p.text);
    for (const p of withText) {
      html += '<p class="verse">' + renderPassage(p.text, p.hl, true) + "</p>";
    }
    if (!withText.length) {
      const doc = state.documents.get(ann.docUri);
      html += '<p class="unfetched">' + escapeHtml(contentPendingLabel(doc, passages.length)) + "</p>";
    }
  }

  if (ann.kind === "note" && ann.location && ann.noteTitle && ann.location !== ann.noteTitle) {
    html += '<div class="refs">' + escapeHtml(ann.location) + "</div>";
  }

  html += renderNote(ann);

  if (ann.refs && ann.refs.length) {
    html += '<div class="refs">Linked: ' +
            ann.refs.map((r) => escapeHtml(r.Name || "")).filter(Boolean).join(" · ") +
            "</div>";
  }

  if (ann.tags.length) {
    html += '<div class="card-tags">' +
      ann.tags.map((t) => '<button class="tag" data-tag="' + escapeHtml(t) + '">' +
                          escapeHtml(t) + "</button>").join("") + "</div>";
  }

  card.innerHTML = html;
  return card;
}

function contentPendingLabel(doc, anchorCount) {
  if (!anchorCount) return "No paragraph content at this reference.";
  if (!doc) return "Content not downloaded.";
  if (doc.restricted) return "Content is not available from the Church's site.";
  if (doc.fetchState === "empty") return "No readable text at this source.";
  if (doc.fetchState === "failed") return "Content could not be downloaded.";
  // Downloaded, but this annotation's anchors are not in the current version.
  if (doc.fetchState === "cached") return "This highlight is not in the current version of the page.";
  return "Content not downloaded — open to fetch it.";
}

function renderMore() {
  const frag = document.createDocumentFragment();
  const end = Math.min(state.shown + PAGE_SIZE, state.results.length);
  for (let i = state.shown; i < end; i++) frag.appendChild(renderCard(state.results[i]));
  el.results.appendChild(frag);
  state.shown = end;
  const left = state.results.length - state.shown;
  el.more.hidden = left <= 0;
  el.more.textContent = "Show " + Math.min(left, PAGE_SIZE) + " more (" + left + " left)";
}

/* --------------------------------------------------------------- content */

const inFlight = new Map();

/* One request per document even if it is opened twice in quick succession. */
function fetchDocument(uri) {
  if (inFlight.has(uri)) return inFlight.get(uri);
  const job = (async () => {
    const res = await fetch(CONTENT_API + encodeURIComponent(uri));
    if (!res.ok) {
      // A 404 is permanent (retired content such as Handbook 2), so record it
      // rather than re-fetching it on every build and every warm pass.
      if (res.status === 404 || res.status === 410) {
        const dead = { uri, fetched_at: new Date().toISOString(), canonical_url: null,
                       restricted: false, error: "HTTP " + res.status, paragraphs: [] };
        await idbPut(idb, dead);
        const known = state.documents.get(uri);
        if (known) known.fetchState = "failed";
        postBack(dead);
      }
      throw new Error("HTTP " + res.status);
    }
    const payload = await res.json();
    const doc = {
      uri,
      fetched_at: new Date().toISOString(),
      canonical_url: (payload.meta && payload.meta.canonicalUrl)
        ? CONTENT_ORIGIN + "/study" + payload.meta.canonicalUrl : null,
      restricted: Boolean(payload.restricted),
      paragraphs: parseParagraphs((payload.content && payload.content.body) || ""),
    };
    await idbPut(idb, doc);
    adoptParagraphs(doc);
    refreshContentText();
    postBack(doc);
    return doc;
  })().finally(() => inFlight.delete(uri));
  inFlight.set(uri, job);
  return job;
}

/* Paragraph ids sit on headings as well as <p>, and are not all of the form
   pN -- title29, aside2_p1, figure1_p29, study_summary1, and the opaque
   p_iilzI ids used from 2025 on are all real annotation targets. DOM order is
   authoritative because the ids are neither contiguous nor monotonic. */
function parseParagraphs(body) {
  const doc = new DOMParser().parseFromString(body, "text/html");
  const out = [];
  doc.querySelectorAll('p[id], h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]').forEach((node) => {
    const id = node.getAttribute("id") || "";
    if (!/^[A-Za-z][\w-]*$/.test(id)) return;
    const text = (node.textContent || "").replace(/\s+/g, " ").trim().normalize("NFC");
    if (!text) return;
    out.push({ para_id: id, pid: node.getAttribute("data-aid") || null, sort: out.length, text });
  });
  return out;
}

/* Only the local dev server has a write-back endpoint. Posting to whatever host
   happens to be serving the app would disclose which talks and manuals the user
   annotated to a third party, so this is confined to loopback rather than being
   attempted everywhere and allowed to fail. */
function isDevServer() {
  return location.hostname === "localhost" || location.hostname === "127.0.0.1"
      || location.hostname === "[::1]";
}

/* Hand the document back to the dev server so the next build embeds it.
   Fire-and-forget: a failure here is never worth surfacing. */
async function postBack(doc) {
  if (!isDevServer()) return;
  try {
    const key = await sha256Hex(doc.uri);
    await fetch("/_cache/" + key, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(doc),
    });
  } catch (err) { /* the dev server may not be the thing serving app/ */ }
}

async function sha256Hex(s) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function isCached(uri) {
  const doc = state.documents.get(uri);
  return Boolean(doc && (doc.fetchState === "cached" || doc.fetchState === "empty"));
}

/* ----------------------------------------------------------------- reader */

function openReader(annId) {
  const ann = state.byId.get(annId);
  if (!ann) return;
  if (ann.kind === "scripture") return openChapterReader(ann);
  if (ann.kind === "document") return openDocumentReader(ann);
}

function showReader(title) {
  el.readerTitle.textContent = title;
  el.reader.hidden = false;
  document.body.style.overflow = "hidden";
  el.readerClose.focus();
}

function openChapterReader(ann) {
  if (!ann.bookId) return;
  state.readerDoc = null;
  const verses = rowsOf(state.db,
    `SELECT verse, text FROM verses WHERE book_id = ${ann.bookId}
      AND chapter = ${ann.chapter} ORDER BY verse`);
  const hlRows = rowsOf(state.db,
    `SELECT annotation_id, verse, word_start, word_end, color, style FROM highlights
      WHERE book_id = ${ann.bookId} AND chapter = ${ann.chapter}`);

  const byVerse = new Map();
  for (const h of hlRows) {
    if (!byVerse.has(h.verse)) byVerse.set(h.verse, []);
    byVerse.get(h.verse).push({ s: h.word_start, e: h.word_end, color: h.color, style: h.style });
  }

  const focus = new Set((state.highlights.get(ann.id) || []).map((h) => h.verse));
  let html = "";
  for (const v of verses) {
    html += '<p class="verse' + (focus.has(v.verse) ? " focus" : "") + '" data-verse="' + v.verse + '">' +
            '<span class="vn">' + v.verse + "</span>" +
            renderPassage(v.text, byVerse.get(v.verse), true) + "</p>";
  }
  el.readerBody.innerHTML = html;
  showReader(ann.book.title + " " + ann.chapter);

  const first = el.readerBody.querySelector(".verse.focus");
  if (first) first.scrollIntoView({ block: "center" });
}

function documentHeaderHtml(ann, doc) {
  const bits = [ann.subtitle, ann.itemTitle, ann.category].filter(Boolean);
  let html = bits.length ? '<div class="byline">' + escapeHtml(bits.join(" · ")) + "</div>" : "";
  const url = (doc && doc.canonicalUrl)
    || CONTENT_ORIGIN + "/study" + (ann.docUri || "") + "?lang=eng";
  html += '<div class="doc-link"><a href="' + escapeHtml(url) +
          '" target="_blank" rel="noopener noreferrer">Open on churchofjesuschrist.org</a></div>';
  return html;
}

function renderDocumentBody(ann, notice) {
  const doc = state.documents.get(ann.docUri);
  let html = documentHeaderHtml(ann, doc);
  if (notice) html += notice;
  // Corpus-derived text may predate a revision of the live page, so it must
  // never be presented as the current wording.
  if (doc && doc.source === "archive") {
    html += '<p class="unfetched">Shown from your local archive, not the live page — ' +
            "the wording may be out of date.</p>";
  }
  const passages = documentPassages(ann);
  const missing = [];
  const context = documentContext(ann, passages);
  if (context) {
    // Whole talk. Context paragraphs carry no highlights of their own, and
    // `.focus` marks which paragraphs are this annotation's -- deliberately the
    // same class the scripture reader uses for focused verses.
    for (const p of context) {
      html += '<p class="verse' + (p.focus ? " focus" : " context") + '">' +
              renderPassage(p.text, p.hl, true) + "</p>";
    }
    // An anchor the current revision dropped is still worth reporting, even
    // though the talk around it rendered fine.
    for (const p of passages) if (!p.text) missing.push(p.paraId);
  } else {
    // Unchanged path: only the annotated paragraphs, so there is nothing to
    // distinguish them from and no `.focus` to apply.
    for (const p of passages) {
      if (p.text) html += '<p class="verse">' + renderPassage(p.text, p.hl, true) + "</p>";
      else missing.push(p.paraId);
    }
  }
  // Say something whenever anything is missing. Gating this on a *partial*
  // miss left the total-miss and empty-document cases rendering a blank panel,
  // while the card for the same annotation explained itself correctly.
  if (missing.length && !notice) {
    html += '<p class="unfetched">' +
            (missing.length === passages.length
              ? escapeHtml(contentPendingLabel(doc, passages.length))
              : missing.length + " highlighted paragraph(s) could not be located in the " +
                "current version of this page.") + "</p>";
  }
  el.readerBody.innerHTML = html;
  // Same as the scripture reader: when the whole unit is on screen, put the
  // annotated part in view rather than leaving the user at the title.
  if (context) {
    const first = el.readerBody.querySelector(".verse.focus");
    if (first) first.scrollIntoView({ block: "center" });
  }
}

async function openDocumentReader(ann) {
  const doc = state.documents.get(ann.docUri);
  state.readerDoc = ann.docUri;
  showReader(ann.location || "Document");

  const passages = documentPassages(ann);
  // Restricted is checked before "already cached": a restricted response
  // carries no paragraphs, so it also looks cached-and-empty, and the empty
  // branch would swallow the explanation.
  if (doc && doc.restricted) {
    renderDocumentBody(ann, '<p class="unfetched">This content is not available from the ' +
      "Church's site.</p>");
    return;
  }
  // Nothing to fetch when the annotation marks no paragraph (a bare reference
  // bookmark), or when the document is already cached -- including a cached
  // document whose anchors all missed, which refetching would not fix.
  if (!passages.length) {
    renderDocumentBody(ann, '<p class="unfetched">No paragraph content at this reference.</p>');
    return;
  }
  if (isCached(ann.docUri)) {
    renderDocumentBody(ann);
    return;
  }
  if (!navigator.onLine) {
    renderDocumentBody(ann, '<p class="unfetched">Not available offline. It will download the ' +
      "next time you open it with a connection.</p>");
    return;
  }

  renderDocumentBody(ann, '<p class="unfetched" id="reader-loading">Downloading content…</p>');
  try {
    await fetchDocument(ann.docUri);
    if (state.readerDoc !== ann.docUri) return;   // user moved on
    const fetched = state.documents.get(ann.docUri);
    if (fetched && fetched.restricted) {
      renderDocumentBody(ann, '<p class="unfetched">This content is not available from the ' +
        "Church's site.</p>");
    } else if (!documentPassages(ann).some((p) => p.text)) {
      // Distinguish "the page has no text" from "this annotation marks no
      // paragraph" -- a bare reference fetches fine and simply has no anchor.
      const label = documentPassages(ann).length
        ? "No readable text at this source."
        : "No paragraph content at this reference.";
      renderDocumentBody(ann, '<p class="unfetched">' + label + "</p>");
    } else {
      renderDocumentBody(ann);
      refreshCards();
    }
  } catch (err) {
    if (state.readerDoc !== ann.docUri) return;
    // Only a permanent status retires the document (fetchDocument records
    // those itself). A 500 or a dropped connection stays retryable, so
    // background warming can still pick it up later.
    renderDocumentBody(ann, '<p class="unfetched">Could not download this content (' +
      escapeHtml(err.message) + '). <button class="link-btn" data-retry="' +
      escapeHtml(ann.id) + '">Retry</button></p>');
  }
}

/* Re-render the cards currently on screen, after content arrives.
   Rebuilding the list changes the page height, which fires `scroll` -- and
   `scroll` counts as user interaction, so this must not be called per
   document or background warming would keep pausing itself. */
function refreshCards() {
  const shown = state.results.slice(0, state.shown);
  if (!shown.length) return;
  const frag = document.createDocumentFragment();
  for (const ann of shown) frag.appendChild(renderCard(ann));
  el.results.innerHTML = "";
  el.results.appendChild(frag);
}

function closeReader() {
  el.reader.hidden = true;
  state.readerDoc = null;
  document.body.style.overflow = "";
}

/* ------------------------------------------------------------- warming */

let idleTimer = null;
/* Transient failures (flaky wifi, a 500) must not retire a document for the
   whole session, so warming counts attempts here instead of marking the
   document 'failed' the way a user-initiated open does. */
const warmAttempts = new Map();
const WARM_MAX_ATTEMPTS = 3;

/* Downloading a thousand documents over someone's phone plan is not a
   background nicety. If the browser will tell us the connection is metered or
   the user asked for reduced data, warming stays off. */
function meteredConnection() {
  const c = navigator.connection;
  if (!c) return false;
  return Boolean(c.saveData) || ["slow-2g", "2g"].includes(c.effectiveType);
}

function warmCandidates() {
  const out = [];
  const seen = new Set();
  for (const ann of state.annotations) {
    if (ann.kind !== "document" || !ann.docUri || seen.has(ann.docUri)) continue;
    seen.add(ann.docUri);
    if (isCached(ann.docUri)) continue;
    const doc = state.documents.get(ann.docUri);
    if (doc && doc.fetchState === "failed") continue;
    if ((warmAttempts.get(ann.docUri) || 0) >= WARM_MAX_ATTEMPTS) continue;
    out.push(ann.docUri);
  }
  return out;
}

function warmStatus(text) {
  el.warmStatus.textContent = text || "";
}

function stopWarming(message) {
  state.warming = false;
  warmStatus(message);
}

/* A loop parked on an in-flight batch cannot be stopped synchronously, so
   `state.warming = false` alone would let a second loop start beside it when
   the idle timer fires. The generation counter retires the old one. */
let warmGeneration = 0;

async function warmLoop() {
  const generation = ++warmGeneration;
  while (state.warming && generation === warmGeneration) {
    if (!navigator.onLine) { stopWarming("paused — offline"); return; }
    if (meteredConnection()) { stopWarming("paused — metered connection"); return; }
    if (state.warmFailures >= WARM_MAX_FAILURES) {
      stopWarming("paused — repeated download failures");
      el.warmToggle.checked = false;
      return;
    }
    const pending = warmCandidates();
    if (!pending.length) {
      stopWarming("all content downloaded");
      el.warmToggle.checked = false;
      return;
    }
    warmStatus(pending.length.toLocaleString() + " left to download");
    const batch = pending.slice(0, WARM_CONCURRENCY);
    const results = await Promise.allSettled(batch.map((uri) => fetchDocument(uri)));
    if (generation !== warmGeneration) return;   // superseded while in flight
    // Consecutive means consecutive: one success anywhere in the batch clears
    // the counter, an all-failed batch advances it by one.
    const failed = results.filter((r) => r.status === "rejected").length;
    state.warmFailures = failed === results.length ? state.warmFailures + 1 : 0;
    let arrived = false;
    batch.forEach((uri, i) => {
      if (results[i].status === "rejected") {
        warmAttempts.set(uri, (warmAttempts.get(uri) || 0) + 1);
      } else {
        arrived = true;
      }
    });
    // One re-render per batch, not per document: refreshCards rebuilds every
    // card currently shown, which can be hundreds.
    if (arrived) refreshCards();
    await new Promise((r) => setTimeout(r, WARM_SPACING_MS));
  }
}

function setWarming(on) {
  state.warming = on;
  if (on) { state.warmFailures = 0; warmLoop(); } else { warmStatus("off"); }
}

/* The toggle records the preference; warming itself only ever starts after the
   idle delay, so enabling it never begins downloading mid-interaction. */
function setWarmPreference(on) {
  try { localStorage.setItem("warmContent", on ? "1" : "0"); } catch (e) { /* private mode */ }
  clearTimeout(idleTimer);
  if (!on) { stopWarming("off"); return; }
  warmStatus("will start when idle");
  idleTimer = setTimeout(() => setWarming(true), WARM_IDLE_MS);
}

/* Warming is for idle time; any interaction pauses it until things settle. */
function noteInteraction() {
  if (!el.warmToggle.checked) return;
  if (state.warming) stopWarming("paused — you're using the app");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    if (el.warmToggle.checked && !state.warming) setWarming(true);
  }, WARM_IDLE_MS);
}

/* ------------------------------------------------------------------- tags */

function countFacetTags(source) {
  const counts = new Map();
  for (const ann of source) {
    for (const tag of ann.tags) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  for (const tag of state.chosenTags) if (!counts.has(tag)) counts.set(tag, 0);
  state.facetTags = [...counts].map(([name, count]) => ({ name, count }));
  state.facetTotal = source.length;
}

function renderTags() {
  const needle = state.tagFilter.toLowerCase();
  const list = state.facetTags.filter((t) => !needle || t.name.toLowerCase().includes(needle));
  list.sort(state.tagSort === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    : (a, b) => b.count - a.count || a.name.localeCompare(b.name));

  const hits = state.tagRegexHits;
  el.tagList.innerHTML = list.slice(0, 300).map((t) =>
    '<button class="tag' + (state.chosenTags.has(t.name) ? " on" : "") +
    (hits && hits.has(t.name) ? " re" : "") + '" data-tag="' +
    escapeHtml(t.name) + '">' + escapeHtml(t.name) + '<span class="n">' + t.count + "</span></button>"
  ).join("");
  if (!list.length) {
    el.tagList.innerHTML = '<span class="tag empty">' +
      (needle ? "No matching tags in these results" : "No tags in these results") + "</span>";
  } else if (list.length > 300) {
    el.tagList.insertAdjacentHTML("beforeend",
      '<span class="tag empty">+' + (list.length - 300) + " more — keep typing</span>");
  }

  el.chosenTags.innerHTML = [...state.chosenTags].map((t) =>
    '<button class="tag on" data-tag="' + escapeHtml(t) + '">' + escapeHtml(t) +
    '<span class="x">&times;</span></button>').join("");

  const narrowing = state.tagMode === "all";
  el.tagModeToggle.textContent = narrowing ? "all" : "any";
  el.tagModeToggle.title = narrowing
    ? "Switch to matching any selected tag"
    : "Switch to requiring every selected tag";
  el.tagModeToggle.setAttribute("aria-label",
    "Matching " + (narrowing ? "all" : "any") + " selected tags. " + el.tagModeToggle.title + ".");

  if (!state.tagRegexSource.trim() || !state.tagRegex) {
    el.tagRegexHint.textContent = "";
  } else {
    el.tagRegexHint.textContent = "matches " + plural(state.tagRegexHits.size, "tag") +
      (state.chosenTags.size
        ? (narrowing ? " · AND with the selected tags" : " · OR with the selected tags")
        : "");
  }

  const hint = [];
  if (state.chosenTags.size) hint.push(state.chosenTags.size + " selected");
  const n = state.facetTags.length.toLocaleString();
  hint.push(narrowing ? n + " in " + plural(state.facetTotal, "result") : n + " you can add");
  el.tagModeHint.textContent = "(" + hint.join(" · ") + ")";
  updateFilterCount();
}

function toggleTag(tag) {
  if (state.chosenTags.has(tag)) state.chosenTags.delete(tag);
  else state.chosenTags.add(tag);
  applyFilters();
}

/* ------------------------------------------------------------- categories */

/* Counts reflect every other active filter but not the type filter itself,
   so a box always shows what ticking it would actually bring in. */
function categoryCounts() {
  const tags = [...state.chosenTags];
  const hits = state.tagRegexHits;
  const searchable = state.query.trim() !== "" && state.matcher !== null;
  const useScripture = scriptureEnabled();
  const counts = new Map();
  for (const ann of state.annotations) {
    if (useScripture && state.volume && String(ann.volumeId) !== state.volume) continue;
    if (useScripture && state.book && String(ann.bookId) !== state.book) continue;
    if (searchable && !annotationMatches(ann)) continue;
    if ((tags.length || hits) && !matchesTagConstraints(ann, tags, hits)) continue;
    counts.set(ann.category, (counts.get(ann.category) || 0) + 1);
  }
  return counts;
}

function renderCategories() {
  const counts = categoryCounts();
  // Update in place when the set of buckets has not changed. Rewriting
  // innerHTML would destroy the checkbox the user just activated, dropping
  // keyboard focus to <body> on every toggle.
  const existing = el.types.querySelectorAll("[data-type]");
  if (existing.length === state.allCategories.length) {
    existing.forEach((box) => {
      const name = box.dataset.type;
      box.checked = !categoryActive() || state.categories.has(name);
      const n = box.parentNode.querySelector(".n");
      if (n) n.textContent = (counts.get(name) || 0).toLocaleString();
    });
  } else {
    el.types.innerHTML = state.allCategories.map((c) => {
      const on = !categoryActive() || state.categories.has(c.name);
      return '<label class="check type"><input type="checkbox" data-type="' + escapeHtml(c.name) +
        '"' + (on ? " checked" : "") + "> " + escapeHtml(c.name) +
        '<span class="n">' + (counts.get(c.name) || 0).toLocaleString() + "</span></label>";
    }).join("");
  }
  // With "all checked" and "none checked" both meaning no constraint, a
  // "select none" action would be a no-op, so the reset only appears when
  // there is something to reset.
  el.typesAll.hidden = !categoryActive();
  el.typesAll.textContent = "Select all";
  el.volumeField.classList.toggle("disabled", !scriptureEnabled());
  el.bookField.classList.toggle("disabled", !scriptureEnabled());
  el.volume.disabled = el.book.disabled = !scriptureEnabled();
}

function toggleCategory(name) {
  // The first click on a box while "all" is showing means "only this one",
  // which is what an all-checked list implies you are narrowing from.
  if (!categoryActive()) {
    state.categories = new Set(state.allCategories.map((c) => c.name));
  }
  if (state.categories.has(name)) state.categories.delete(name);
  else state.categories.add(name);
  if (state.categories.size === state.allCategories.length) state.categories.clear();
  applyFilters();
}

function showFilters(open) {
  el.filters.hidden = !open;
  el.filtersToggle.setAttribute("aria-expanded", String(open));
}

function updateFilterCount() {
  const n = state.chosenTags.size + (state.volume ? 1 : 0) + (state.book ? 1 : 0) +
            (categoryActive() ? 1 : 0) + (state.tagRegex ? 1 : 0);
  el.filterCount.hidden = n === 0;
  el.filterCount.textContent = n;
}

function renderBookOptions() {
  const vol = state.volume;
  const books = [...state.books.values()]
    .filter((b) => !vol || String(b.volumeId) === vol)
    .sort((a, b) => a.sort - b.sort);
  el.book.innerHTML = '<option value="">All books</option>' +
    books.map((b) => '<option value="' + b.id + '">' + escapeHtml(b.title) + "</option>").join("");
  if (state.book && !books.some((b) => String(b.id) === state.book)) state.book = "";
  el.book.value = state.book;
}

/* ------------------------------------------------------------------ export */

async function exportContent() {
  const docs = await idbAll(idb);
  if (!docs.length) {
    warmStatus("nothing fetched yet to export");
    return;
  }
  const blob = new Blob(
    [JSON.stringify({ version: EXPORT_VERSION, exported: new Date().toISOString(), documents: docs })],
    { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "scripture-notes-content.json";
  // Attached and revoked on a later tick: some browsers cancel a download
  // whose anchor was never in the document, or whose blob URL is revoked
  // synchronously after the click.
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 0);
  warmStatus("exported " + plural(docs.length, "document"));
}

/* ------------------------------------------------------------------ wiring */

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function wire() {
  const rerun = debounce(applyFilters, 160);

  el.q.addEventListener("input", () => {
    state.query = el.q.value;
    el.qClear.hidden = !state.query;
    rerun();
  });
  el.qClear.addEventListener("click", () => {
    el.q.value = ""; state.query = ""; el.qClear.hidden = true; el.q.focus(); applyFilters();
  });

  document.querySelectorAll("[data-searchin]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.searchIn = btn.dataset.searchin;
      document.querySelectorAll("[data-searchin]").forEach((b) => b.classList.toggle("on", b === btn));
      applyFilters();
    });
  });
  el.tagModeToggle.addEventListener("click", () => {
    state.tagMode = state.tagMode === "all" ? "any" : "all";
    applyFilters();
  });
  document.querySelectorAll("[data-tagsort]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.tagSort = btn.dataset.tagsort;
      document.querySelectorAll("[data-tagsort]").forEach((b) => b.classList.toggle("on", b === btn));
      renderTags();
    });
  });

  $("#opt-regex").addEventListener("change", (e) => { state.regex = e.target.checked; applyFilters(); });
  $("#opt-case").addEventListener("change", (e) => { state.caseSensitive = e.target.checked; applyFilters(); });

  el.filtersToggle.addEventListener("click", () => showFilters(el.filters.hidden));

  el.volume.addEventListener("change", (e) => {
    state.volume = e.target.value; renderBookOptions(); updateFilterCount(); applyFilters();
  });
  el.book.addEventListener("change", (e) => {
    state.book = e.target.value; updateFilterCount(); applyFilters();
  });
  el.types.addEventListener("change", (e) => {
    const box = e.target.closest("[data-type]");
    if (box) toggleCategory(box.dataset.type);
  });
  el.typesAll.addEventListener("click", () => {
    state.categories.clear();            // back to no constraint
    applyFilters();
  });
  el.tagRegex.addEventListener("input", debounce((e) => {
    state.tagRegexSource = e.target.value;
    applyFilters();
  }, 160));
  el.sortSel.addEventListener("change", (e) => { state.sort = e.target.value; applyFilters(); });

  el.tagSearch.addEventListener("input", debounce((e) => {
    state.tagFilter = e.target.value; renderTags();
  }, 120));
  el.tagsClear.addEventListener("click", () => {
    state.chosenTags.clear(); applyFilters();
  });

  el.warmToggle.addEventListener("change", (e) => setWarmPreference(e.target.checked));
  el.exportBtn.addEventListener("click", exportContent);

  const onTagClick = (e) => {
    const btn = e.target.closest("[data-tag]");
    if (btn) toggleTag(btn.dataset.tag);
  };
  el.tagList.addEventListener("click", onTagClick);
  el.chosenTags.addEventListener("click", onTagClick);

  // Any click outside the header gets the filter panel out of the way.
  // Capture phase on purpose: clicking a chip re-renders the list, which
  // detaches the clicked node, and a detached node reports no .topbar ancestor.
  document.addEventListener("click", (e) => {
    if (!el.filters.hidden && !e.target.closest(".topbar")) showFilters(false);
  }, true);

  document.querySelector("main").addEventListener("click", (e) => {
    const open = e.target.closest("[data-open]");
    if (open) { openReader(open.dataset.open); return; }
    const tag = e.target.closest("[data-tag]");
    if (tag) toggleTag(tag.dataset.tag);
  });

  el.readerBody.addEventListener("click", (e) => {
    const retry = e.target.closest("[data-retry]");
    if (retry) {
      const ann = state.byId.get(retry.dataset.retry);
      const doc = ann && state.documents.get(ann.docUri);
      if (doc) doc.fetchState = "unfetched";
      if (ann) openDocumentReader(ann);
    }
  });

  el.more.addEventListener("click", renderMore);
  el.readerClose.addEventListener("click", closeReader);
  el.reader.addEventListener("click", (e) => { if (e.target === el.reader) closeReader(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.reader.hidden) closeReader();
    if (e.key === "/" && document.activeElement !== el.q && !e.metaKey && !e.ctrlKey) {
      e.preventDefault(); el.q.focus();
    }
  });

  for (const evt of ["click", "keydown", "input", "scroll"]) {
    document.addEventListener(evt, noteInteraction, { passive: true });
  }
  window.addEventListener("online", () => {
    if (el.warmToggle.checked && !state.warming) setWarmPreference(true);
  });
  window.addEventListener("offline", () => {
    if (state.warming) stopWarming("paused — offline");
  });
}

/* -------------------------------------------------------------------- boot */

(async function main() {
  try {
    await load();
    el.volume.innerHTML = '<option value="">All volumes</option>' +
      state.volumes.map((v) => '<option value="' + v.id + '">' + escapeHtml(v.title) + "</option>").join("");
    renderBookOptions();
    wire();
    applyFilters();

    let warmPref = null;
    try { warmPref = localStorage.getItem("warmContent"); } catch (e) { /* private mode */ }
    if (warmPref === "1") { el.warmToggle.checked = true; setWarmPreference(true); }
    else warmStatus("off");
  } catch (err) {
    el.status.innerHTML = "Failed to load: " + escapeHtml(err.message);
    console.error(err);
  }
})();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("service-worker.js")
    .catch((e) => console.warn("service worker not registered:", e)));
}
