const CACHE = "politometro-public-20260613-171432";
const HTML_PATHS = new Set(["/", "/index.html", "/privacy.html", "/metodo.html", "/supporto.html", "/organizzazioni.html"]);
const CORE = ["./manifest.webmanifest", "./icon.svg", "./icon-192.png", "./icon-512.png", "./og-image.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(CORE)));
  self.skipWaiting();
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/") || url.pathname === "/admin" || url.pathname.startsWith("/admin/") || url.pathname === "/login" || url.pathname.startsWith("/login/")) return;
  if (request.mode === "navigate" || HTML_PATHS.has(url.pathname)) {
    event.respondWith(fetch(request, { cache: "no-store" }).catch(() => caches.match("./index.html")));
    return;
  }
  event.respondWith(fetch(request).then(response => {
    if (!response || !response.ok || response.type === "opaque") return response;
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(request, copy));
    return response;
  }).catch(() => caches.match(request).then(cached => cached || caches.match("./index.html"))));
});
