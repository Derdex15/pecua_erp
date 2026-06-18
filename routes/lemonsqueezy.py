# routes/lemonsqueezy.py
"""
Integración Lemon Squeezy — ERP Pecuario
Suscripción mensual recurrente a $4.99/mes

Variables de entorno en Render:
  LS_VARIANT_ID     → 1805965
  LS_STORE_SLUG     → erpecuario
  LS_WEBHOOK_SECRET → secreto del webhook (de LS → Ajustes → Webhooks)
  APP_URL           → https://erpecuario.com

Webhook a configurar en Lemon Squeezy → Ajustes → Webhooks:
  URL: https://erpecuario.com/webhook/lemonsqueezy
  Eventos: subscription_created, subscription_payment_success,
           subscription_cancelled, subscription_expired
"""
import os
import hmac
import hashlib
import json
import datetime
from flask import Blueprint, redirect, session, request
from config import sb_get, sb_post, sb_patch
from routes.permisos import login_required, get_granja_info

bp = Blueprint("lemonsqueezy", __name__)

LS_VARIANT_ID    = os.getenv("LS_VARIANT_ID",    "1805965")
LS_STORE_SLUG    = os.getenv("LS_STORE_SLUG",    "erpecuario")
LS_CHECKOUT_UUID = os.getenv("LS_CHECKOUT_UUID", "2b6d6ce7-2aee-4b8d-ab2f-8f658cdff24e")
LS_WEBHOOK_SECRET = os.getenv("LS_WEBHOOK_SECRET", "")
APP_URL          = os.getenv("APP_URL", "https://erpecuario.com")

PRECIO_MENSUAL = 4.99


# ── Redirigir al checkout de Lemon Squeezy ────────────────────────────────────

@bp.route("/checkout/lemonsqueezy")
@login_required
def checkout():
    """
    Redirige al checkout de Lemon Squeezy con el email y user_id pre-rellenos.
    El user_id se pasa como custom_data para que el webhook sepa a quién activar.
    """
    owner_id, _ = get_granja_info(session["user_id"])

    # Obtener email del usuario (para pre-rellenar el checkout)
    usuario = sb_get("usuarios", f"id=eq.{owner_id}")
    email   = (usuario[0].get("email", "") if usuario else "") or ""

    # Build checkout URL con UUID correcto
    base_url = f"https://{LS_STORE_SLUG}.lemonsqueezy.com/checkout/buy/{LS_CHECKOUT_UUID}"
    params = [f"checkout[custom][user_id]={owner_id}"]
    if email:
        params.append(f"checkout[email]={email}")

    return redirect(f"{base_url}?{'&'.join(params)}", code=303)


# ── Webhook de Lemon Squeezy ──────────────────────────────────────────────────

@bp.route("/webhook/lemonsqueezy", methods=["POST"])
def webhook():
    """
    Recibe eventos de Lemon Squeezy y activa/desactiva Premium
    según el estado de la suscripción.
    """
    body      = request.get_data()
    signature = request.headers.get("X-Signature", "")

    # Verificar firma HMAC-SHA256
    if LS_WEBHOOK_SECRET:
        expected = hmac.new(
            LS_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            print("[LS WEBHOOK] Firma inválida — rechazado")
            return "Invalid signature", 403

    try:
        data = json.loads(body)
    except Exception:
        return "Invalid JSON", 400

    meta        = data.get("meta", {})
    event       = meta.get("event_name", "")
    custom_data = meta.get("custom_data", {})
    user_id     = custom_data.get("user_id")

    print(f"[LS WEBHOOK] Evento: {event} | user_id: {user_id}")

    if not user_id:
        print(f"[LS WEBHOOK] Sin user_id en custom_data: {custom_data}")
        return "OK", 200

    attrs           = data.get("data", {}).get("attributes", {})
    ls_sub_id       = str(data.get("data", {}).get("id", ""))
    status          = attrs.get("status", "")

    # ── Activar premium ───────────────────────────────────────────
    if event in ("subscription_created",
                 "subscription_payment_success",
                 "order_created"):
        _activar_premium(user_id, ls_sub_id, event)

    # ── Cancelación solicitada (sigue activa hasta vencer) ────────
    elif event == "subscription_cancelled":
        sb_patch("suscripciones", f"usuario_id=eq.{user_id}",
                 {"cancelar_al_vencer": True})
        print(f"[LS] Cancelación marcada para user {user_id}")

    # ── Suscripción vencida ────────────────────────────────────────
    elif event == "subscription_expired":
        sb_patch("suscripciones", f"usuario_id=eq.{user_id}",
                 {"activa": False, "plan": "free"})
        print(f"[LS] Suscripción expirada para user {user_id}")

    # ── Reactivación (si el usuario re-suscribe) ──────────────────
    elif event == "subscription_resumed":
        _activar_premium(user_id, ls_sub_id, event)

    return "OK", 200


# ── Helpers ───────────────────────────────────────────────────────────────────

def _activar_premium(user_id, ls_sub_id: str, evento: str):
    """Activa o renueva el plan Premium para el usuario dado."""
    hoy        = datetime.date.today()
    # 32 días para dar margen al ciclo mensual de LS
    nueva_fecha = hoy + datetime.timedelta(days=32)

    existente = sb_get("suscripciones", f"usuario_id=eq.{user_id}")

    datos = {
        "plan":              "premium",
        "activa":            True,
        "fecha_inicio":      str(hoy),
        "fecha_fin":         str(nueva_fecha),
        "metodo_pago":       "lemonsqueezy",
        "cancelar_al_vencer": False,
    }

    if existente:
        # Si ya hay suscripción activa, extender desde la fecha actual
        fecha_actual = existente[0].get("fecha_fin", "")
        if fecha_actual and fecha_actual > str(hoy):
            base        = datetime.date.fromisoformat(fecha_actual)
            nueva_fecha = base + datetime.timedelta(days=32)
            datos["fecha_fin"] = str(nueva_fecha)
        sb_patch("suscripciones", f"usuario_id=eq.{user_id}", datos)
    else:
        sb_post("suscripciones", {"usuario_id": user_id, **datos})

    # Registrar el pago
    sb_post("pagos", {
        "usuario_id":      user_id,
        "monto":           PRECIO_MENSUAL,
        "meses":           1,
        "estado":          "completado",
        "metodo":          "lemonsqueezy",
        "referencia_pago": ls_sub_id or evento,
    })

    print(f"[LS] Premium activado para user {user_id} — vence {nueva_fecha}")