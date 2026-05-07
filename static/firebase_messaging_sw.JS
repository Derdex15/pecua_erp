// firebase-messaging-sw.js
// ──────────────────────────────────────────────────────────────
// Service Worker DEDICADO a Firebase Cloud Messaging.
//
// IMPORTANTE: Este archivo DEBE estar en la raíz del sitio,
// accesible en https://TU_DOMINIO.com/firebase-messaging-sw.js
//
// En Flask, añade esta ruta en app.py:
//   @app.route("/firebase-messaging-sw.js")
//   def firebase_sw():
//       return send_from_directory("static", "firebase-messaging-sw.js",
//                                  mimetype="application/javascript")
//
// Coloca el archivo en: static/firebase-messaging-sw.js
// ──────────────────────────────────────────────────────────────

importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js');

// ── REEMPLAZA estos valores con los de tu proyecto Firebase ───
// Los obtienes en: Firebase Console → Configuración del proyecto → General
firebase.initializeApp({
    apiKey:            "FIREBASE_API_KEY",
    authDomain:        "FIREBASE_AUTH_DOMAIN",
    projectId:         "FIREBASE_PROJECT_ID",
    storageBucket:     "FIREBASE_STORAGE_BUCKET",
    messagingSenderId: "FIREBASE_SENDER_ID",
    appId:             "FIREBASE_APP_ID",
});

const messaging = firebase.messaging();

// ── Manejo de mensajes en BACKGROUND (app cerrada o en otra pestaña) ──
messaging.onBackgroundMessage(payload => {
    console.log('[FCM-SW] Mensaje recibido en background:', payload);

    const notif  = payload.notification || {};
    const titulo = notif.title || '🐄 ERP Pecuario';
    const cuerpo = notif.body  || 'Tienes una alerta pendiente.';
    const icono  = notif.icon  || '/static/icons/icon-192.png';
    const urlDestino = payload.data?.url || '/alertas';

    self.registration.showNotification(titulo, {
        body:             cuerpo,
        icon:             icono,
        badge:            '/static/icons/icon-192.png',
        tag:              'erp-alerta',   // agrupa notificaciones — solo muestra la más reciente
        renotify:         true,           // vibra aunque ya haya una con el mismo tag
        requireInteraction: false,        // se cierra sola después de un rato
        data: { url: urlDestino },
    });
});

// ── Clic en la notificación: abrir o enfocar la app ───────────
self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = event.notification.data?.url || '/alertas';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(lista => {
                // Si ya hay una pestaña abierta, navegar en ella
                for (const client of lista) {
                    if ('focus' in client) {
                        client.navigate(url);
                        return client.focus();
                    }
                }
                // Si no hay pestaña abierta, abrir una nueva
                return clients.openWindow(url);
            })
    );
});