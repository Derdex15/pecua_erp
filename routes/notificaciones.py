# routes/notificaciones.py
"""
Notificaciones Push — ERP Pecuario  (FCM HTTP v1 API)

MIGRACIÓN desde Legacy API:
  La URL https://fcm.googleapis.com/fcm/send fue deprecada por Google en
  junio 2024. Este módulo usa la nueva HTTP v1 API autenticada con OAuth2
  mediante una Service Account de Firebase.

VARIABLES DE ENTORNO necesarias (Render → Environment):
  FIREBASE_PROJECT_ID            → ID del proyecto Firebase
                                   Ej: erp-pecuario1
  FIREBASE_SERVICE_ACCOUNT_JSON  → Contenido íntegro del JSON de la
                                   Service Account (ver instrucciones abajo)

Endpoints públicos:
  POST /api/save_token              ← guarda token FCM desde base.html
  POST /api/push_token              ← alias de compatibilidad
  POST /api/push_token/desactivar   ← desactiva token al cerrar sesión
  GET  /api/alertas_count           ← badge del navbar
  GET  /ping                        ← keepalive UptimeRobot (Render Free)

Función interna:
  enviar_push(owner_id, titulo, cuerpo, url="/alertas")
    → importar desde cualquier blueprint para enviar notificaciones

══════════════════════════════════════════════════════════════════════════
INSTRUCCIONES PARA CONFIGURAR FIREBASE SERVICE ACCOUNT (hazlo tú):

  1. Ve a Firebase Console → ⚙️ Configuración del Proyecto
  2. Pestaña "Cuentas de Servicio"
  3. Clic en "Generar nueva clave privada" → descarga el JSON
  4. En Render.com → tu servicio → Environment, agrega:

       FIREBASE_SERVICE_ACCOUNT_JSON  = <pega el JSON completo aquí>
       FIREBASE_PROJECT_ID            = erp-pecuario1

     Render preserva saltos de línea en el valor, no necesitas escaparlos.

  5. En tu .env LOCAL agrega las mismas variables para pruebas.
  6. NUNCA subas el archivo JSON al repositorio.
══════════════════════════════════════════════════════════════════════════
"""
import os
import json
import time
import requests as http
from flask import Blueprint, request, session, jsonify
from config import sb_get, sb_post, sb_patch
from routes.permisos import get_granja_info

bp = Blueprint("notificaciones", __name__)

PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FCM_V1_URL = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"

# Cache del access token OAuth2 para no pedirlo en cada push
_oauth_cache = {"token": None, "expiry": 0.0}


def _get_oauth_token() -> str | None:
    """
    Obtiene un access token OAuth2 usando la Service Account de Firebase.
    Cachea el token hasta 5 minutos antes de su expiración (~55 min de vida útil).
    Retorna None si FIREBASE_SERVICE_ACCOUNT_JSON no está configurada.
    """
    # Usar token cacheado si sigue vigente
    if _oauth_cache["token"] and time.time() < _oauth_cache["expiry"]:
        return _oauth_cache["token"]

    sa_json_str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_str:
        print("⚠️  FIREBASE_SERVICE_ACCOUNT_JSON no configurada — push desactivado")
        return None

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleRequest

        sa_info = json.loads(sa_json_str)
        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        credentials.refresh(GoogleRequest())

        expiry_ts = (credentials.expiry.timestamp()
                     if credentials.expiry else time.time() + 3300)
        _oauth_cache["token"]  = credentials.token
        _oauth_cache["expiry"] = expiry_ts - 300   # refrescar 5 min antes
        return credentials.token

    except Exception as e:
        print(f"❌ Error obteniendo token OAuth2 FCM: {e}")
        return None


# ── Helper: guardar o actualizar token FCM ───────────────────────────────────
def _upsert_token(owner_id: int, token: str) -> bool:
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@bp.route("/api/save_token", methods=["POST"])
def save_token():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "no autenticado"}), 401

    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token vacío"}), 400

    owner_id, _ = get_granja_info(session["user_id"])
    ok = _upsert_token(owner_id, token)
    return jsonify({"ok": ok})


@bp.route("/api/push_token", methods=["POST"])
def push_token():
    """Alias de /api/save_token por compatibilidad con código antiguo."""
    return save_token()


@bp.route("/api/push_token/desactivar", methods=["POST"])
def desactivar_token():
    if "user_id" not in session:
        return jsonify({"ok": False}), 401
    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if token:
        sb_patch("push_tokens", f"token=eq.{token}", {"activo": False})
    return jsonify({"ok": True})


@bp.route("/api/alertas_count")
def alertas_count():
    if "user_id" not in session:
        return jsonify({"count": 0})
    owner_id, _ = get_granja_info(session["user_id"])
    alertas = sb_get("alertas", f"usuario_id=eq.{owner_id}&leida=eq.false")
    return jsonify({"count": len(alertas)})


@bp.route("/ping")
def ping():
    return jsonify({"status": "ok", "service": "erp-pecuario"}), 200


# ── enviar_push() — función interna ──────────────────────────────────────────
def enviar_push(owner_id: int, titulo: str, cuerpo: str,
                url: str = "/alertas") -> dict:
    """
    Envía notificación push a todos los dispositivos activos del owner_id.
    Usa FCM HTTP v1 API con OAuth2.

    Uso desde cualquier blueprint:
        from routes.notificaciones import enviar_push
        enviar_push(owner_id, "💉 Vacuna", "Aftosa vence mañana")

    Retorna:
        { "enviadas": int, "fallidas": int, "sin_tokens": bool, "error"?: str }
    """
    if not PROJECT_ID:
        return {"enviadas": 0, "fallidas": 0, "sin_tokens": True,
                "error": "FIREBASE_PROJECT_ID no configurado"}

    oauth_token = _get_oauth_token()
    if not oauth_token:
        return {"enviadas": 0, "fallidas": 0, "sin_tokens": True,
                "error": "Service Account no configurada"}

    tokens = sb_get("push_tokens", f"usuario_id=eq.{owner_id}&activo=eq.true")
    if not tokens:
        return {"enviadas": 0, "fallidas": 0, "sin_tokens": True}

    enviadas = 0
    fallidas = 0

    for t in tokens:
        payload = {
            "message": {
                "token": t["token"],
                "notification": {
                    "title": titulo,
                    "body":  cuerpo,
                },
                "webpush": {
                    "fcm_options": {"link": url},
                    "notification": {
                        "title":              titulo,
                        "body":               cuerpo,
                        "icon":               "/static/icons/icon-192.png",
                        "badge":              "/static/icons/icon-192.png",
                        "require_interaction": True,
                    }
                }
            }
        }
        try:
            res = http.post(
                FCM_V1_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {oauth_token}",
                    "Content-Type":  "application/json",
                },
                timeout=(5, 10),
            )
            if res.status_code == 200:
                enviadas += 1
            else:
                fallidas += 1
                error_data = res.json()
                error_code = (error_data.get("error", {})
                              .get("details", [{}])[0]
                              .get("errorCode", ""))
                # Token inválido o expirado → desactivar para no volver a intentar
                if error_code in ("UNREGISTERED", "INVALID_ARGUMENT"):
                    sb_patch("push_tokens",
                             f"token=eq.{t['token']}", {"activo": False})
                    print(f"🗑  Token inválido desactivado: {t['token'][:20]}…")
                else:
                    print(f"⚠️  FCM {res.status_code}: {res.text[:200]}")
        except Exception as e:
            fallidas += 1
            print(f"❌ Error enviando push: {e}")

    return {"enviadas": enviadas, "fallidas": fallidas, "sin_tokens": False}