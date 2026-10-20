// Minimal service worker: makes the app installable and caches the UI shell.
const CACHE = "insta-mealie-v1";
const SHELL = ["/", "/static/style.css", "/static/app.js", "/static/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  // Network first (always fresh UI), cache as offline fallback. "/?text=…" maps to "/".
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(url.pathname, copy));
        return res;
      })
      .catch(() => caches.match(url.pathname))
  );
});
