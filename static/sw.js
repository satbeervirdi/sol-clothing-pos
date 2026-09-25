// Service Worker for SOL POS PWA
const CACHE_NAME = 'sol-pos-cache-v2';
const ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/sol_logo.svg',
  '/static/sol_logo.png',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/og-banner.png'
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
