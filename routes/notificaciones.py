# routes/notificaciones.py
"""
Notificaciones Push FCM — ERP Pecuario

Endpoints:
  POST /api/save_token    ← nombre que usa el frontend (base.html)
  POST /api/push_token    ← alias por compatibilidad
  POST /api/push_token/desactivar
  GET  /api/alertas_count ← badge del navbar (sin token)
  GET  /ping              ← keepalive para plan Free de Render
"""
import os
import requests as http
from flask import Blueprint, request, session, jsonify
from config import sb_get, sb_post, sb_patch
from routes.permisos import get_granja_info

bp = Blueprint("notificaciones", __name__)

FCM_URL    = "https://fcm.googleapis.com/fcm/send"
SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")


# ── Helper interno: guardar o actualizar token ─────────────────
def _upsert_token(owner_id: int, token: str) -> bool:
    """Inserta o actualiza el token FCM en Supabase. Retorna True si tuvo éxito."""
    if not token:
        return False
    existente = sb_get("push_tokens", f"token=eq.{token}")
    if existente:
        sb_patch("push_tokens", f"token=eq.{token}", {
            "usuario_id": owner_id,
            "activo":     True,
        })
    else:
        sb_post("push_tokens", {
            "usuario_id": owner_id,
            "token":      token,
            "plataforma": "web",
            "activo":     True,
        })
    return True


# ── /api/save_token  (nombre que usa base.html) ────────────────
@bp.route("/api/save_token", methods=["POST"])
def save_token():
    """
    Endpoint principal que llama el frontend desde base.html.
    Body JSON: { "token": "<fcm_token>" }
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "no autenticado"}), 401

    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()

    if not token:
        return jsonify({"ok": False, "error": "token vacío"}), 400

    owner_id, _ = get_granja_info(session["user_id"])
    ok = _upsert_token(owner_id, token)
    return jsonify({"ok": ok})


# ── /api/push_token  (alias por compatibilidad) ────────────────
@bp.route("/api/push_token", methods=["POST"])
def push_token():
    """Alias de /api/save_token — ambos hacen exactamente lo mismo."""
    return save_token()


# ── /api/push_token/desactivar ─────────────────────────────────
@bp.route("/api/push_token/desactivar", methods=["POST"])
def desactivar_token():
    """Marca un token como inactivo cuando el usuario revoca el permiso."""
    if "user_id" not in session:
        return jsonify({"ok": False}), 401

    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if token:
        sb_patch("push_tokens", f"token=eq.{token}", {"activo": False})
    return jsonify({"ok": True})


# ── /ping  — keepalive para evitar cold start en Render Free ───
@bp.route("/ping")
def ping():
    """
    Endpoint de salud ligero.
    El plan Free de Render hiberna tras 15 min de inactividad.
    Para evitarlo, configura un cron externo (UptimeRobot / cron-job.org)
    que llame a GET https://TU_DOMINIO.onrender.com/ping cada 14 minutos.
    UptimeRobot es gratuito y lo hace automáticamente.
    """
    return jsonify({"status": "ok", "service": "erp-pecuario"}), 200


# ── enviar_push()  — función interna usada por otros blueprints ─
def enviar_push(owner_id: int, titulo: str, cuerpo: str, url: str = "/alertas") -> dict:
    """
    Envía notificación push a todos los dispositivos activos del owner_id.

    Uso desde cualquier blueprint:
        from routes.notificaciones import enviar_push
        enviar_push(owner_id, "💉 Vacuna", "Aftosa vence mañana")

    Retorna: { "enviadas": int, "fallidas": int, "sin_tokens": bool }
    """
    if not SERVER_KEY:
        print("⚠️  FCM_SERVER_KEY no configurada — push desactivado")
        return {"enviadas": 0, "fallidas": 0, "sin_tokens": True,
                "error": "FCM_SERVER_KEY no configurada"}

    tokens = sb_get("push_tokens", f"usuario_id=eq.{owner_id}&activo=eq.true")
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
            },
            "webpush": {
                "fcm_options": {"link": url},
                "notification": {
                    "title": titulo,
                    "body":  cuerpo,
                    "icon":  "/static/icons/icon-192.png",
                    "badge": "/static/icons/icon-192.png",
                    "requireInteraction": True,
                }
            }
        }
        try:
            res  = http.post(
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
                # Token inválido → desactivar para no volver a intentar
                errores_invalidos = ("NotRegistered", "InvalidRegistration")
                if (data.get("results") and
                        data["results"][0].get("error") in errores_invalidos):
                    sb_patch("push_tokens",
                             f"token=eq.{t['token']}", {"activo": False})
                    print(f"🗑  Token inválido desactivado: {t['token'][:20]}…")
        except Exception as e:
            fallidas += 1
            print(f"❌ Error enviando push a token {t['token'][:20]}…: {e}")

    return {"enviadas": enviadas, "fallidas": fallidas, "sin_tokens": False}