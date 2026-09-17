/* Only a public, data-free offline document and build assets enter Cache Storage.
   Bump this version with shell changes. API, uploads, auth and other HTML are NEVER cached. */
const VERSION = "vfc-shell-20260917-1";
const SHELL = "/mobile/offline";
self.addEventListener("install", event => event.waitUntil((async () => {
  const cache = await caches.open(VERSION);
  const response = await fetch(SHELL, {cache: "reload", credentials: "omit"});
  if (!response.ok) throw new Error("Offline shell unavailable");
  const html = await response.clone().text();
  const assets = [...new Set([...html.matchAll(/(?:src|href)="([^"<>]+)"/g)].map(m => m[1].replaceAll("&amp;", "&")).filter(p => p.startsWith("/_next/static/")))];
  await cache.addAll([...assets, "/icons/icon-192.png", "/icons/icon-512.png", "/manifest.webmanifest"]);
  await cache.put(SHELL, response);
})()));
self.addEventListener("activate", event => event.waitUntil((async () => {
  // Retain older build assets until tabs close; no forced reload can discard unsaved work.
  const clients = await self.clients.matchAll({type: "window", includeUncontrolled: true});
  if (!clients.length) for (const name of await caches.keys()) if(name.startsWith("vfc-shell-") && name !== VERSION) await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener("message", event => { if (event.data?.type === "ACTIVATE_UPDATE") self.skipWaiting(); });
self.addEventListener("fetch", event => {
  const request = event.request; const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(async () => {
      if (url.pathname !== SHELL) return Response.redirect(new URL(SHELL, self.location.origin), 302);
      return (await caches.open(VERSION)).match(SHELL);
    }));
  } else if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith((async () => {
      const cached = await caches.match(request); if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && response.type === "basic") { const cache = await caches.open(VERSION); await cache.put(request, response.clone()); }
      return response;
    })());
  }
});
