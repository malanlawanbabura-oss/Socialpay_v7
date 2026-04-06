// SocialPay Service Worker v3
const CACHE_NAME = 'socialpay-v3';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/js/app.js',
  '/login'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // Network first for API/dynamic, cache fallback for static
  if (event.request.url.includes('/api/') || event.request.method === 'POST') {
    return; // Don't cache API/POST
  }
  event.respondWith(
    fetch(event.request).catch(() =>
      caches.match(event.request)
    )
  );
});
