/* Cache-first shell + dataset so the app works offline once loaded.
   Bump CACHE whenever the shell or data.sqlite is rebuilt. */

const CACHE = "scripture-notes-v4";   // bumped: documents/paragraphs schema + content fetch
const CONTENT_CACHE = "scripture-notes-content-v1";
const CONTENT_ORIGIN = "https://www.churchofjesuschrist.org";
const CONTENT_PATH = "/study/api/v3/language-pages/type/content";
const ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
  "./vendor/sql-wasm.js",
  "./vendor/sql-wasm.wasm",
  "./data/app.sqlite",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((k) => k !== CACHE && k !== CONTENT_CACHE)
        .map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* The shell (html/css/js) is small and changes often, so go to the network first
   and fall back to cache when offline -- otherwise an edit stays invisible until
   the cache name is bumped. Big immutable assets stay cache-first. */
const SHELL = /\.(html|css|js)$/;

function isShell(url) {
  return url.pathname.endsWith("/") || SHELL.test(url.pathname);
}

async function store(request, response) {
  if (response.ok && new URL(request.url).origin === self.location.origin) {
    const cache = await caches.open(CACHE);
    await cache.put(request, response.clone());
  }
  return response;
}

/* The Gospel Library content API is the one cross-origin host we touch. It gets
   a network-first route so revised pages are picked up, falling back to the
   cached copy offline. Everything else cross-origin still passes straight
   through -- this must not become a general cross-origin proxy. */
function isContentApi(url) {
  return url.origin === CONTENT_ORIGIN && url.pathname === CONTENT_PATH;
}

/* The app already keeps every fetched document in IndexedDB, so this cache is
   only an offline safety net for reloads. Without a bound it would grow into a
   second full copy of the corpus, so keep it to the most recent entries. */
const CONTENT_CACHE_MAX = 300;
let trimming = false;

async function trimContentCache(cache) {
  if (trimming) return;
  trimming = true;
  try {
    const keys = await cache.keys();
    for (let i = 0; i < keys.length - CONTENT_CACHE_MAX; i++) await cache.delete(keys[i]);
  } finally {
    trimming = false;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (isContentApi(url)) {
    event.respondWith(
      fetch(request)
        .then(async (res) => {
          if (res.ok) {
            const cache = await caches.open(CONTENT_CACHE);
            await cache.put(request, res.clone());
            trimContentCache(cache);
          }
          return res;
        })
        .catch(() => caches.match(request).then((hit) => hit || Response.error()))
    );
    return;
  }

  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate" || isShell(url)) {
    event.respondWith(
      fetch(request)
        .then((res) => store(request, res))
        .catch(() => caches.match(request).then((hit) => hit || caches.match("./index.html")))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => hit ||
      fetch(request).then((res) => store(request, res)))
  );
});
