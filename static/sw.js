// Service Worker — ERP Pecuario
// Versión con soporte FCM para notificaciones push en background

importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js');

// ── Configuración Firebase ────────────────────────────────────
// Estos valores vienen de tu proyecto Firebase (ver NOTIFICACIONES.md)
// NO son secretos — son identificadores públicos del proyecto.
const FIREBASE_CONFIG = {
    apiKey:            self.FIREBASE_API_KEY            || "REEMPLAZAR",
    authDomain:        self.FIREBASE_AUTH_DOMAIN        || "REEMPLAZAR",
    projectId:         self.FIREBASE_PROJECT_ID         || "REEMPLAZAR",
    storageBucket:     self.FIREBASE_STORAGE_BUCKET     || "REEMPLAZAR",
    messagingSenderId: self.FIREBASE_MESSAGING_SENDER_ID || "REEMPLAZAR",
    appId:             self.FIREBASE_APP_ID             || "REEMPLAZAR",
};

firebase.initializeApp(FIREBASE_CONFIG);
const messaging = firebase.messaging();

// ── Cache para modo offline ───────────────────────────────────
const CACHE_NAME = 'erp-pecuario-v3';

const CACHE_ESTATICO = [
    '/',
    '/inventario',
    '/movimientos',
    '/gastos',
    '/sanitario',
    '/bajas',
    '/animales',
    '/manifest.json',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache =>
            cache.addAll(CACHE_ESTATICO).catch(err => console.log('Cache parcial:', err))
        )
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

// ── Fetch: Network First con fallback a cache ─────────────────
self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    if (event.request.url.includes('supabase.co')) return;
    if (event.request.url.includes('fcm.googleapis.com')) return;

    const url = new URL(event.request.url);
    if (['/login', '/logout', '/registro'].includes(url.pathname)) return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                if (response.ok) {
                    const copia = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copia));
                }
                return response;
            })
            .catch(() =>
                caches.match(event.request).then(cached => {
                    if (cached) return cached;
                    return new Response(`
                        <!DOCTYPE html>
                        <html><head>
                            <meta name="viewport" content="width=device-width,initial-scale=1">
                            <title>Sin conexión</title>
                            <style>
                                body{font-family:Arial;text-align:center;padding:40px 20px;background:#f4f6f9;}
                                .card{background:white;padding:30px;border-radius:12px;max-width:380px;margin:0 auto;box-shadow:0 2px 5px rgba(0,0,0,.1);}
                                button{background:#27ae60;color:white;padding:12px 24px;border:none;border-radius:8px;font-size:15px;cursor:pointer;margin-top:15px;}
                            </style>
                        </head>
                        <body>
                            <div class="card">
                                <div style="font-size:60px;">📡</div>
                                <h2>Sin conexión</h2>
                                <p style="color:gray;">Revisa tu señal e intenta de nuevo.</p>
                                <button onclick="window.location.reload()">🔄 Reintentar</button>
                            </div>
                        </body></html>
                    `, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
                })
            )
    );
});

// ── Notificaciones push en background (app cerrada) ───────────
// Firebase maneja automáticamente los mensajes en background.
// Este handler muestra la notificación cuando llega un mensaje FCM
// mientras la app NO está abierta en primer plano.
messaging.onBackgroundMessage(payload => {
    console.log('📬 Push en background:', payload);

    const { title, body, icon } = payload.notification || {};

    self.registration.showNotification(title || '🐄 ERP Pecuario', {
        body:    body  || 'Tienes una alerta pendiente.',
        icon:    icon  || '/static/icons/icon-192.png',
        badge:        '/static/icons/icon-192.png',
        tag:          'erp-pecuario-alerta',  // agrupa notificaciones del mismo tipo
        renotify:     true,
        data: {
            url: payload.data?.url || '/alertas',
        },
    });
});

// ── Clic en notificación: abrir la app ────────────────────────
self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = event.notification.data?.url || '/alertas';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(clientList => {
                // Si ya hay una ventana abierta, enfocarla
                for (const client of clientList) {
                    if (client.url.includes(self.location.origin) && 'focus' in client) {
                        client.navigate(url);
                        return client.focus();
                    }
                }
                // Si no hay ventana, abrir una nueva
                return clients.openWindow(url);
            })
    );
});