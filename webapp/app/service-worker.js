/* Cache-first shell + dataset so the app works offline once loaded.
   Bump CACHE whenever the shell or data.sqlite is rebuilt. */

const CACHE = "scripture-notes-v3";   // bumped: app.sqlite rebuilt with corrected highlight offsets
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
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
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

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
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
