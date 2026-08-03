/* Scripture Notes -- offline annotation browser.
   Loads a prebuilt SQLite file with sql.js and does all filtering in memory. */

const DB_URL = "data/app.sqlite";
const PAGE_SIZE = 40;

const state = {
  db: null,
  annotations: [],
  byId: new Map(),
  highlights: new Map(),   // annotation id -> [{verse, s, e, color, style}]
  verseText: new Map(),    // "bookId:chapter:verse" -> text
  books: new Map(),        // bookId -> {id, title, volumeId, url, sort}
  volumes: [],
  tags: [],
  query: "",
  scope: "both",
  regex: false,
  caseSensitive: false,
  volume: "",
  book: "",
  kind: "",
  sort: "recent",
  tagMode: "any",
  tagSort: "count",
  chosenTags: new Set(),
  tagFilter: "",
  results: [],
  shown: 0,
  matcher: null,
};

const $ = (sel) => document.querySelector(sel);
const el = {
  status: $("#status"),
  results: $("#results"),
  more: $("#more"),
  q: $("#q"),
  qClear: $("#q-clear"),
  regexErr: $("#regex-err"),
  filters: $("#filters"),
  filtersToggle: $("#filters-toggle"),
  filterCount: $("#filter-count"),
  volume: $("#f-volume"),
  book: $("#f-book"),
  kind: $("#f-kind"),
  sortSel: $("#f-sort"),
  tagSearch: $("#tag-search"),
  tagList: $("#tag-list"),
  chosenTags: $("#chosen-tags"),
  tagsClear: $("#tags-clear"),
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

function verseKey(bookId, chapter, verse) {
  return bookId + ":" + chapter + ":" + verse;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/* Word index (1-based, inclusive) -> character range in the verse text.
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

/* ------------------------------------------------------------------ load */

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
  state.tags = rowsOf(db, "SELECT name, count FROM tags ORDER BY count DESC, name");

  for (const h of rowsOf(db, `SELECT annotation_id, book_id, chapter, verse, word_start, word_end,
                                     color, style FROM highlights`)) {
    let list = state.highlights.get(h.annotation_id);
    if (!list) state.highlights.set(h.annotation_id, (list = []));
    list.push({ bookId: h.book_id, chapter: h.chapter, verse: h.verse,
                s: h.word_start, e: h.word_end, color: h.color, style: h.style });
  }

  for (const v of rowsOf(db, `SELECT DISTINCT v.book_id, v.chapter, v.verse, v.text
                              FROM verses v JOIN highlights h
                                ON h.book_id = v.book_id AND h.chapter = v.chapter
                               AND h.verse = v.verse`)) {
    state.verseText.set(verseKey(v.book_id, v.chapter, v.verse), v.text);
  }

  for (const a of rowsOf(db, `SELECT id, kind, type, location, item_title, book_id, chapter,
                                     verse_start, verse_end, note_title, note_text, verse_text,
                                     tags, refs_json, created, updated, sort_date
                              FROM annotations`)) {
    const book = a.book_id ? state.books.get(a.book_id) : null;
    const ann = {
      id: a.id,
      kind: a.kind,
      type: a.type,
      location: a.location || a.note_title || "Note",
      itemTitle: a.item_title || "",
      bookId: a.book_id,
      book,
      volumeId: book ? book.volumeId : null,
      chapter: a.chapter,
      verseStart: a.verse_start,
      verseEnd: a.verse_end,
      noteTitle: a.note_title || "",
      noteText: a.note_text || "",
      verseText: a.verse_text || "",
      tags: a.tags ? a.tags.split(", ") : [],
      tagSet: new Set(a.tags ? a.tags.split(", ") : []),
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

  const meta = {};
  for (const r of rowsOf(db, "SELECT key, value FROM meta")) meta[r.key] = r.value;
  return meta;
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

function testMatch(text) {
  if (!text) return false;
  state.matcher.lastIndex = 0;
  return state.matcher.test(text);
}

function annotationMatches(ann) {
  if (!state.matcher) return true;
  const notes = state.scope !== "verses" && testMatch(ann.noteBlob);
  const verses = state.scope !== "notes" && testMatch(ann.verseText);
  return Boolean(notes || verses);
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

function applyFilters() {
  buildMatcher();
  const searchable = state.query.trim() !== "" && state.matcher !== null;
  const tags = [...state.chosenTags];

  state.results = state.annotations.filter((ann) => {
    if (state.kind === "scripture" && ann.kind !== "scripture") return false;
    if (state.kind === "note" && ann.kind !== "note") return false;
    if (state.kind === "withnote" && !ann.hasNote) return false;
    if (state.volume && String(ann.volumeId) !== state.volume) return false;
    if (state.book && String(ann.bookId) !== state.book) return false;
    if (tags.length) {
      const hit = state.tagMode === "all"
        ? tags.every((t) => ann.tagSet.has(t))
        : tags.some((t) => ann.tagSet.has(t));
      if (!hit) return false;
    }
    if (searchable && !annotationMatches(ann)) return false;
    return true;
  });

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

/* Render one verse, layering scripture highlights and search matches.
   Both are char ranges over the same text, so they are merged per character. */
function renderVerse(text, highlights, showMatches) {
  const marks = new Array(text.length).fill(null);
  for (const h of highlights || []) {
    const range = wordRangeToChars(text, h.s, h.e);
    if (!range) continue;
    for (let i = range[0]; i < range[1]; i++) marks[i] = h;
  }

  const hits = new Array(text.length).fill(false);
  if (showMatches && state.matcher) {
    const scopeAllows = state.scope !== "notes";
    if (scopeAllows) {
      for (const [s, e] of matchRanges(text)) {
        for (let i = s; i < e; i++) hits[i] = true;
      }
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
  if (state.matcher && state.scope !== "verses") {
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

function renderCard(ann) {
  const card = document.createElement("article");
  card.className = "card";

  const meta = [];
  if (ann.kind === "note") meta.push(ann.type === "journal" ? "Journal" : "Note");
  if (ann.itemTitle && ann.kind === "scripture") meta.push(ann.itemTitle);
  const date = formatDate(ann.sortDate);
  if (date) meta.push(date);

  const head = ann.kind === "scripture"
    ? '<button class="ref-btn" data-open="' + escapeHtml(ann.id) + '">' +
        escapeHtml(ann.location) + "</button>"
    : '<span class="ref-btn" style="color:var(--text)">' +
        escapeHtml(ann.noteTitle || ann.location) + "</span>";

  let html = '<div class="card-head">' + head +
             '<span class="card-meta">' + escapeHtml(meta.join(" · ")) + "</span></div>";

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
              renderVerse(text, byVerse.get(key), true) + "</p>";
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

/* ----------------------------------------------------------------- reader */

function openReader(annId) {
  const ann = state.byId.get(annId);
  if (!ann || !ann.bookId) return;

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
  el.readerTitle.textContent = ann.book.title + " " + ann.chapter;

  let html = "";
  for (const v of verses) {
    html += '<p class="verse' + (focus.has(v.verse) ? " focus" : "") + '" data-verse="' + v.verse + '">' +
            '<span class="vn">' + v.verse + "</span>" +
            renderVerse(v.text, byVerse.get(v.verse), true) + "</p>";
  }
  el.readerBody.innerHTML = html;
  el.reader.hidden = false;
  document.body.style.overflow = "hidden";

  const first = el.readerBody.querySelector(".verse.focus");
  if (first) first.scrollIntoView({ block: "center" });
  el.readerClose.focus();
}

function closeReader() {
  el.reader.hidden = true;
  document.body.style.overflow = "";
}

/* ------------------------------------------------------------------- tags */

function renderTags() {
  const needle = state.tagFilter.toLowerCase();
  const list = state.tags.filter((t) => !needle || t.name.toLowerCase().includes(needle));
  list.sort(state.tagSort === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    : (a, b) => b.count - a.count || a.name.localeCompare(b.name));
  el.tagList.innerHTML = list.slice(0, 300).map((t) =>
    '<button class="tag' + (state.chosenTags.has(t.name) ? " on" : "") + '" data-tag="' +
    escapeHtml(t.name) + '">' + escapeHtml(t.name) + '<span class="n">' + t.count + "</span></button>"
  ).join("");
  if (list.length > 300) {
    el.tagList.insertAdjacentHTML("beforeend",
      '<span class="tag" style="border:0">+' + (list.length - 300) + " more — keep typing</span>");
  }

  el.chosenTags.innerHTML = [...state.chosenTags].map((t) =>
    '<button class="tag on" data-tag="' + escapeHtml(t) + '">' + escapeHtml(t) +
    '<span class="x">&times;</span></button>').join("");
  el.tagModeHint.textContent = state.chosenTags.size
    ? "(" + state.chosenTags.size + " selected, match " + state.tagMode + ")"
    : "";
  updateFilterCount();
}

function toggleTag(tag) {
  if (state.chosenTags.has(tag)) state.chosenTags.delete(tag);
  else state.chosenTags.add(tag);
  renderTags();
  applyFilters();
}

function updateFilterCount() {
  const n = state.chosenTags.size + (state.volume ? 1 : 0) + (state.book ? 1 : 0) +
            (state.kind ? 1 : 0);
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

  document.querySelectorAll("[data-scope]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.scope = btn.dataset.scope;
      document.querySelectorAll("[data-scope]").forEach((b) => b.classList.toggle("on", b === btn));
      applyFilters();
    });
  });
  document.querySelectorAll("[data-tagmode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.tagMode = btn.dataset.tagmode;
      document.querySelectorAll("[data-tagmode]").forEach((b) => b.classList.toggle("on", b === btn));
      renderTags();
      applyFilters();
    });
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

  el.filtersToggle.addEventListener("click", () => {
    const open = el.filters.hidden;
    el.filters.hidden = !open;
    el.filtersToggle.setAttribute("aria-expanded", String(open));
  });

  el.volume.addEventListener("change", (e) => {
    state.volume = e.target.value; renderBookOptions(); updateFilterCount(); applyFilters();
  });
  el.book.addEventListener("change", (e) => {
    state.book = e.target.value; updateFilterCount(); applyFilters();
  });
  el.kind.addEventListener("change", (e) => {
    state.kind = e.target.value; updateFilterCount(); applyFilters();
  });
  el.sortSel.addEventListener("change", (e) => { state.sort = e.target.value; applyFilters(); });

  el.tagSearch.addEventListener("input", debounce((e) => {
    state.tagFilter = e.target.value; renderTags();
  }, 120));
  el.tagsClear.addEventListener("click", () => {
    state.chosenTags.clear(); renderTags(); applyFilters();
  });

  const onTagClick = (e) => {
    const btn = e.target.closest("[data-tag]");
    if (btn) toggleTag(btn.dataset.tag);
  };
  el.tagList.addEventListener("click", onTagClick);
  el.chosenTags.addEventListener("click", onTagClick);

  el.results.addEventListener("click", (e) => {
    const open = e.target.closest("[data-open]");
    if (open) { openReader(open.dataset.open); return; }
    const tag = e.target.closest("[data-tag]");
    if (tag) {
      if (el.filters.hidden) {
        el.filters.hidden = false;
        el.filtersToggle.setAttribute("aria-expanded", "true");
      }
      toggleTag(tag.dataset.tag);
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
}

/* -------------------------------------------------------------------- boot */

(async function main() {
  try {
    await load();
    el.volume.innerHTML = '<option value="">All volumes</option>' +
      state.volumes.map((v) => '<option value="' + v.id + '">' + escapeHtml(v.title) + "</option>").join("");
    renderBookOptions();
    renderTags();
    wire();
    applyFilters();
  } catch (err) {
    el.status.innerHTML = "Failed to load: " + escapeHtml(err.message);
    console.error(err);
  }
})();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("service-worker.js")
    .catch((e) => console.warn("service worker not registered:", e)));
}
