// Service Worker for SOL POS PWA
const CACHE_NAME = 'sol-pos-cache-v1';
const ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/sol_logo.jpg'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((k) => {
          if (k !== CACHE_NAME) return caches.delete(k);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  // Let network requests through, fallback to cache
  if (e.request.url.includes('/api/')) {
    return; // Don't cache dynamic API calls
  }
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
