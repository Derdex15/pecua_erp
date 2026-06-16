# routes/paypal.py
"""
Integración PayPal Orders API v2 — ERP Pecuario

Variables de entorno necesarias en Render:
  PAYPAL_CLIENT_ID  → Client ID de tu cuenta PayPal Business
  PAYPAL_SECRET     → Secret de tu cuenta PayPal Business
  PAYPAL_MODE       → live  (o sandbox para pruebas)
  APP_URL           → https://erpecuario.com
"""
import os
import datetime
import requests as http
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from routes.permisos import login_required, get_granja_info
from config import sb_get, sb_post, sb_patch

bp = Blueprint("paypal", __name__)

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET    = os.getenv("PAYPAL_SECRET", "")
PAYPAL_MODE      = os.getenv("PAYPAL_MODE", "live")
APP_URL          = os.getenv("APP_URL", "https://erpecuario.com")

PAYPAL_BASE = ("https://api-m.paypal.com" if PAYPAL_MODE == "live"
               else "https://api-m.sandbox.paypal.com")

PLANES = {
    "1":  {"label": "1 mes",    "precio": "5.00",  "descuento": 0},
    "3":  {"label": "3 meses",  "precio": "13.50", "descuento": 10},
    "6":  {"label": "6 meses",  "precio": "24.00", "descuento": 20},
    "12": {"label": "12 meses", "precio": "42.00", "descuento": 30},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_access_token() -> str | None:
    """Obtiene un token de acceso de PayPal."""
    try:
        res = http.post(
            f"{PAYPAL_BASE}/v1/oauth2/token",
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=(5, 10),
        )
        return res.json().get("access_token")
    except Exception as e:
        print(f"[PAYPAL] Error obteniendo token: {e}")
        return None


def _crear_orden(meses: str, owner_id) -> dict | None:
    """Crea una orden de pago en PayPal."""
    plan  = PLANES[meses]
    token = _get_access_token()
    if not token:
        return None

    try:
        res = http.post(
            f"{PAYPAL_BASE}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {
                        "currency_code": "USD",
                        "value": plan["precio"],
                    },
                    "description": f"ERP Pecuario Premium — {plan['label']}",
                    "custom_id":   f"{owner_id}:{meses}",
                }],
                "application_context": {
                    "brand_name":          "ERP Pecuario",
                    "landing_page":        "BILLING",
                    "user_action":         "PAY_NOW",
                    "return_url":          f"{APP_URL}/paypal/capturar",
                    "cancel_url":          f"{APP_URL}/planes",
                    "shipping_preference": "NO_SHIPPING",
                },
            },
            timeout=(5, 15),
        )
        data = res.json()
        if res.status_code == 201:
            return data
        print(f"[PAYPAL] Error creando orden: {data}")
        return None
    except Exception as e:
        print(f"[PAYPAL] Error: {e}")
        return None


def _capturar_orden(order_id: str) -> dict | None:
    """Captura el pago de una orden aprobada."""
    token = _get_access_token()
    if not token:
        return None

    try:
        res = http.post(
            f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=(5, 15),
        )
        return res.json() if res.status_code == 201 else None
    except Exception as e:
        print(f"[PAYPAL] Error capturando orden: {e}")
        return None


def _activar_premium(owner_id, meses: int, referencia: str, monto: float):
    """Activa o extiende el plan premium."""
    hoy       = datetime.date.today()
    existente = sb_get("suscripciones", f"usuario_id=eq.{owner_id}")

    if existente:
        fecha_actual = existente[0].get("fecha_fin")
        base = (datetime.date.fromisoformat(fecha_actual)
                if fecha_actual and fecha_actual > str(hoy) else hoy)
        nueva_fecha = base + datetime.timedelta(days=30 * meses)
        sb_patch("suscripciones", f"usuario_id=eq.{owner_id}", {
            "plan":         "premium",
            "activa":       True,
            "fecha_inicio": str(hoy),
            "fecha_fin":    str(nueva_fecha),
            "metodo_pago":  "paypal",
        })
    else:
        nueva_fecha = hoy + datetime.timedelta(days=30 * meses)
        sb_post("suscripciones", {
            "usuario_id":   owner_id,
            "plan":         "premium",
            "activa":       True,
            "fecha_inicio": str(hoy),
            "fecha_fin":    str(nueva_fecha),
            "metodo_pago":  "paypal",
        })

    sb_post("pagos", {
        "usuario_id":      owner_id,
        "referencia_pago": referencia,
        "monto":           monto,
        "meses":           meses,
        "estado":          "completado",
        "metodo":          "paypal",
    })

    return nueva_fecha


# ── Iniciar checkout ──────────────────────────────────────────────────────────

@bp.route("/paypal/checkout/<meses>", methods=["POST"])
@login_required
def checkout(meses):
    if meses not in PLANES:
        flash("Plan inválido.", "error")
        return redirect("/planes")

    if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET:
        flash("PayPal no está configurado aún.", "error")
        return redirect("/planes")

    owner_id, _ = get_granja_info(session["user_id"])
    orden       = _crear_orden(meses, owner_id)

    if not orden:
        flash("Error al conectar con PayPal. Intenta de nuevo.", "error")
        return redirect("/planes")

    # Guardar en sesión para validar al volver
    session["pp_order_id"] = orden["id"]
    session["pp_meses"]    = meses
    session["pp_owner"]    = owner_id

    # Buscar el link de aprobación
    for link in orden.get("links", []):
        if link["rel"] == "approve":
            return redirect(link["href"], code=303)

    flash("No se pudo obtener el link de pago de PayPal.", "error")
    return redirect("/planes")


# ── Capturar pago al volver de PayPal ────────────────────────────────────────

@bp.route("/paypal/capturar")
@login_required
def capturar():
    order_id = request.args.get("token", "")  # PayPal llama "token" al order_id
    payer_id = request.args.get("PayerID", "")

    # Recuperar y limpiar sesión
    ses_order = session.pop("pp_order_id", None)
    meses     = session.pop("pp_meses",    None)
    pp_owner  = session.pop("pp_owner",    None)

    owner_id, _ = get_granja_info(session["user_id"])

    # Validaciones de seguridad
    if not ses_order or not meses:
        flash("Sesión de pago expirada. Si fuiste cobrado contáctanos.", "error")
        return redirect("/planes")

    if order_id != ses_order:
        print(f"[PAYPAL SOSPECHOSO] order_url={order_id} != order_ses={ses_order}")
        flash("Error de validación del pago. Contacta soporte.", "error")
        return redirect("/planes")

    if pp_owner and pp_owner != owner_id:
        print(f"[PAYPAL SOSPECHOSO] owner cambió: {pp_owner} → {owner_id}")
        flash("Error de validación. Contacta soporte.", "error")
        return redirect("/planes")

    if not payer_id:
        flash("Pago cancelado. Puedes intentarlo nuevamente.", "error")
        return redirect("/planes")

    # Capturar el pago con PayPal
    resultado = _capturar_orden(order_id)

    if not resultado or resultado.get("status") != "COMPLETED":
        estado = resultado.get("status") if resultado else "sin respuesta"
        print(f"[PAYPAL] Captura fallida — status={estado} order={order_id}")
        flash("El pago no fue confirmado por PayPal. "
              "Si ves el cobro en tu cuenta contáctanos.", "error")
        return redirect("/planes")

    # Extraer monto real cobrado
    try:
        monto = float(
            resultado["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"]
        )
    except (KeyError, IndexError, ValueError):
        monto = float(PLANES.get(meses, {}).get("precio", 0))

    # Activar premium
    nueva_fecha = _activar_premium(
        owner_id,
        meses       = int(meses),
        referencia  = order_id,
        monto       = monto,
    )

    plan = PLANES.get(meses, {})
    flash(f"¡Plan {plan.get('label','Premium')} activado hasta el "
          f"{nueva_fecha.strftime('%d/%m/%Y')}! Bienvenido a Premium 🎉", "success")
    return redirect("/")