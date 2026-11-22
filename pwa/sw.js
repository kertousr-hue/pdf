/* PDF Éditeur (PWA) — service worker : garde l'application pour l'utiliser hors ligne.
 * La version et la liste des fichiers sont remplies par pwa/construire.py.
 */
"use strict";

const VERSION = "pdf-editeur-__VERSION__";
const FICHIERS = __FICHIERS__;

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    // fichiers téléchargés un par un : une coupure ne fait pas tout recommencer
    for (const f of FICHIERS) {
      if (!(await cache.match(f))) {
        const r = await fetch(f, { cache: "no-cache" });
        if (r.ok) await cache.put(f, r);
      }
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const nom of await caches.keys()) if (nom !== VERSION) await caches.delete(nom);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const trouve = await cache.match(req, { ignoreSearch: true });
    if (trouve) return trouve;
    try {
      const r = await fetch(req);
      if (r.ok && r.type === "basic") cache.put(req, r.clone());
      return r;
    } catch (err) {
      if (req.mode === "navigate") return (await cache.match("./")) || (await cache.match("index.html"));
      throw err;
    }
  })());
});
