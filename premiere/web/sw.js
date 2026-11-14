// Cache léger : l'app s'ouvre même avec un réseau faible ; les données viennent toujours de Supabase.
const CACHE = "premiere-v1";
const FICHIERS = ["./", "index.html", "style.css", "app.js", "config.js", "manifest.webmanifest", "icon.svg", "icon-180.png", "icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FICHIERS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((cles) => Promise.all(cles.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then((rep) => {
      const copie = rep.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copie));
      return rep;
    }).catch(() => caches.match(e.request))
  );
});
