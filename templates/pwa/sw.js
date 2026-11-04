{% load static %}// Service worker d'Aptitude Support (rendu par Django pour connaître les adresses des fichiers statiques).
// Règle de sécurité : les pages et les données ne sont JAMAIS mises en cache sur l'appareil.
// Seuls l'habillage (styles, images, scripts) et la page « hors ligne » le sont.
const CACHE = "aptitude-shell-{{ version }}";
const OFFLINE_URL = "{% url 'offline' %}";
const SHELL = [
  OFFLINE_URL,
  "{% static 'css/app.css' %}",
  "{% static 'js/mobile.js' %}",
  "{% static 'img/logo.png' %}",
  "{% static 'img/logo-white.png' %}",
  "{% static 'img/mark.png' %}",
  "{% static 'img/icon-192.png' %}",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("aptitude-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Pages : toujours le réseau. Sans réseau, la page « hors ligne » (aucune donnée en cache).
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  // Fichiers statiques (adresses versionnées) : cache d'abord, puis réseau.
  if (url.pathname.startsWith("{% get_static_prefix %}")) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      }))
    );
  }
});
