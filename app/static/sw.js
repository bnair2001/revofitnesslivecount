// Service Worker for Revo Fitness Live Count PWA
const CACHE_NAME = 'revo-fitness-v1.2.0';
const STATIC_CACHE = 'revo-static-v1.2.0';
const DYNAMIC_CACHE = 'revo-dynamic-v1.2.0';

// Files to cache immediately
const STATIC_FILES = [
  '/',
  '/static/manifest.json',
  '/favicon.ico',
  // Add critical CSS/JS files if they exist as static files
  '/static/icon-192x192.png',
  '/static/icon-512x512.png'
];

// API endpoints that should be cached with network-first strategy
const API_ENDPOINTS = [
  '/_dash-update-component',
  '/_dash-dependencies',
  '/_dash-layout'
];

// Install event - cache static files
self.addEventListener('install', (event) => {
  console.log('Service Worker installing...');
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {
        console.log('Caching static files...');
        return cache.addAll(STATIC_FILES.filter(url => url !== '/'));
      })
      .then(() => {
        console.log('Static files cached successfully');
        return self.skipWaiting();
      })
      .catch((error) => {
        console.error('Failed to cache static files:', error);
      })
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  console.log('Service Worker activating...');
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            if (cacheName !== STATIC_CACHE && cacheName !== DYNAMIC_CACHE) {
              console.log('Deleting old cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      })
      .then(() => {
        console.log('Service Worker activated');
        return self.clients.claim();
      })
  );
});

// Fetch event - implement caching strategies
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Handle different types of requests with appropriate strategies
  if (request.method === 'GET') {
    // Static files - cache first
    if (STATIC_FILES.includes(url.pathname)) {
      event.respondWith(cacheFirst(request));
    }
    // API calls - network first with fallback
    else if (API_ENDPOINTS.some(endpoint => url.pathname.includes(endpoint))) {
      event.respondWith(networkFirst(request));
    }
    // Main app - network first with cache fallback
    else if (url.pathname === '/' || url.pathname === '') {
      event.respondWith(networkFirst(request));
    }
    // Other resources - stale while revalidate
    else {
      event.respondWith(staleWhileRevalidate(request));
    }
  }
});

// Cache strategies
async function cacheFirst(request) {
  try {
    const cachedResponse = await caches.match(request);
    return cachedResponse || fetch(request);
  } catch (error) {
    console.error('Cache first failed:', error);
    return fetch(request);
  }
}

async function networkFirst(request) {
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    console.log('Network failed, trying cache:', error);
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    // Return offline page for navigation requests
    if (request.mode === 'navigate') {
      return new Response(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Revo Fitness - Offline</title>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body { 
              font-family: Arial, sans-serif; 
              text-align: center; 
              padding: 50px; 
              background: linear-gradient(135deg, #007bff, #0056b3);
              color: white;
              margin: 0;
              min-height: 100vh;
              display: flex;
              flex-direction: column;
              justify-content: center;
            }
            .offline-icon { font-size: 4rem; margin-bottom: 1rem; }
            h1 { margin-bottom: 1rem; }
            p { font-size: 1.1rem; margin-bottom: 2rem; }
            button { 
              background: white; 
              color: #007bff; 
              border: none; 
              padding: 12px 24px; 
              border-radius: 6px;
              font-size: 1rem;
              cursor: pointer;
              box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            button:hover { background: #f8f9fa; }
          </style>
        </head>
        <body>
          <div class="offline-icon">📱</div>
          <h1>You're Offline</h1>
          <p>Revo Fitness Live Count needs an internet connection to show current gym data.</p>
          <button onclick="window.location.reload()">Try Again</button>
        </body>
        </html>
      `, {
        status: 200,
        headers: { 'Content-Type': 'text/html' }
      });
    }
    throw error;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(DYNAMIC_CACHE);
  const cachedResponse = await cache.match(request);
  
  const fetchPromise = fetch(request).then((networkResponse) => {
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  });

  return cachedResponse || fetchPromise;
}

// Background sync for when connection is restored
self.addEventListener('sync', (event) => {
  console.log('Background sync triggered:', event.tag);
  // Could implement data sync here when connection is restored
});

// Push notifications (for future enhancement)
self.addEventListener('push', (event) => {
  if (event.data) {
    const options = {
      body: event.data.text(),
      icon: '/static/icon-192x192.png',
      badge: '/static/icon-72x72.png',
      vibrate: [200, 100, 200],
      data: {
        url: '/'
      }
    };
    
    event.waitUntil(
      self.registration.showNotification('Revo Fitness Update', options)
    );
  }
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url || '/')
  );
});