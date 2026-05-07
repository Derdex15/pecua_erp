# routes/notificaciones.py
"""
Notificaciones Push FCM — ERP Pecuario

Flujo:
  1. El frontend pide permiso al usuario (base.html)
  2. Si acepta, Firebase SDK retorna un token de registro
  3. El frontend llama a POST /api/push_token para guardarlo en Supabase
  4. Cuando el backend quiere notificar, llama a enviar_push() con el owner_id
  5. FCM entrega la notificación al dispositivo, incluso con la app cerrada

Requiere en .env:
  FCM_SERVER_KEY   = tu server key de Firebase (proyecto > Configuración > Cloud Messaging)
  FIREBASE_SENDER_ID = tu sender ID (aparece en la misma pantalla)
"""
import os
import requests as http
from flask import Blueprint, request, session, jsonify
from config import sb_get, sb_post, sb_patch
from routes.permisos import get_granja_info

bp = Blueprint("notificaciones", __name__)

FCM_URL    = "https://fcm.googleapis.com/fcm/send"
SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")


# ── Guardar / actualizar token del dispositivo ─────────────────
@bp.route("/api/push_token", methods=["POST"])
def guardar_token():
    """
    Llamado por el frontend cuando obtiene un nuevo token FCM.
    Body JSON: { "token": "<fcm_token>" }
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "no autenticado"}), 401

    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token vacío"}), 400

    owner_id, _ = get_granja_info(session["user_id"])

    # Upsert: si el token ya existe, actualizarlo; si no, crearlo
    existente = sb_get("push_tokens", f"token=eq.{token}")
    if existente:
        sb_patch("push_tokens", f"token=eq.{token}", {
            "usuario_id": owner_id,
            "activo":     True,
            "updated_at": "now()",
        })
    else:
        sb_post("push_tokens", {
            "usuario_id": owner_id,
            "token":      token,
            "plataforma": "web",
            "activo":     True,
        })

    return jsonify({"ok": True})


# ── Desactivar token (cuando el usuario lo revoca) ─────────────
@bp.route("/api/push_token/desactivar", methods=["POST"])
def desactivar_token():
    if "user_id" not in session:
        return jsonify({"ok": False}), 401

    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if token:
        sb_patch("push_tokens", f"token=eq.{token}", {"activo": False})
    return jsonify({"ok": True})


# ── Función interna para enviar push desde el backend ──────────
def enviar_push(owner_id: int, titulo: str, cuerpo: str, url: str = "/alertas") -> dict:
    """
    Envía una notificación push a todos los dispositivos activos del owner_id.

    Retorna dict con { enviadas, fallidas, sin_tokens }.
    Llama esta función desde sanitario.py o cualquier blueprint que genere alertas.

    Ejemplo de uso:
        from routes.notificaciones import enviar_push
        enviar_push(owner_id, "💉 Vacuna pendiente", "Aftosa — Lote Cerdos A vence mañana")
    """
    if not SERVER_KEY:
        return {"enviadas": 0, "fallidas": 0, "sin_tokens": True,
                "error": "FCM_SERVER_KEY no configurada en .env"}

    tokens = sb_get("push_tokens",
                    f"usuario_id=eq.{owner_id}&activo=eq.true")
    if not tokens:
        return {"enviadas": 0, "fallidas": 0, "sin_tokens": True}

    enviadas = 0
    fallidas = 0

    for t in tokens:
        payload = {
            "to": t["token"],
            "notification": {
                "title": titulo,
                "body":  cuerpo,
                "icon":  "/static/icons/icon-192.png",
                "click_action": url,
            },
            "webpush": {
                "fcm_options": {"link": url}
            }
        }
        try:
            res = http.post(
                FCM_URL,
                json=payload,
                headers={
                    "Authorization": f"key={SERVER_KEY}",
                    "Content-Type":  "application/json",
                },
                timeout=(5, 10),
            )
            data = res.json()
            if data.get("success", 0) >= 1:
                enviadas += 1
            else:
                fallidas += 1
                # Si el token ya no es válido, desactivarlo
                if data.get("results") and \
                   data["results"][0].get("error") in (
                       "NotRegistered", "InvalidRegistration"):
                    sb_patch("push_tokens",
                             f"token=eq.{t['token']}", {"activo": False})
        except Exception as e:
            fallidas += 1
            print(f"❌ Error enviando push: {e}")

    return {"enviadas": enviadas, "fallidas": fallidas, "sin_tokens": False}