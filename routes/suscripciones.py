# routes/suscripciones.py
"""
Suscripciones y Pagos — ERP Pecuario
Pasarela: PayPhone (Ecuador)

Variables de entorno necesarias en Render:
  PAYPHONE_TOKEN    -> Token de tu cuenta PayPhone
  PAYPHONE_STORE_ID -> ID del Store en PayPhone
  APP_URL           -> https://pecua-erp.onrender.com
"""
import os
import datetime
import requests as http
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch
from routes.permisos import get_granja_info, es_premium_owner

bp = Blueprint("suscripciones", __name__)

APP_URL     = os.getenv("APP_URL", "https://pecua-erp.onrender.com")
PP_TOKEN    = os.getenv("PAYPHONE_TOKEN", "")
PP_STORE_ID = os.getenv("PAYPHONE_STORE_ID", "")
PP_API_URL  = "https://pay.payphonetodoesmas.com/api"
DIAS_TRIAL  = 7

PLANES = {
    "1":  {"label": "1 mes",    "precio_usd": 5.00,  "precio_ctvs": 500,  "descuento": 0},
    "3":  {"label": "3 meses",  "precio_usd": 13.50, "precio_ctvs": 1350, "descuento": 10},
    "6":  {"label": "6 meses",  "precio_usd": 24.00, "precio_ctvs": 2400, "descuento": 20},
    "12": {"label": "12 meses", "precio_usd": 42.00, "precio_ctvs": 4200, "descuento": 30},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def dias_restantes(user_id):
    hoy = str(datetime.date.today())
    res = sb_get("suscripciones",
                 f"usuario_id=eq.{user_id}&activa=eq.true&fecha_fin=gte.{hoy}")
    if not res:
        return 0
    return (datetime.date.fromisoformat(res[0]["fecha_fin"]) - datetime.date.today()).days


def tiene_trial_disponible(user_id):
    res = sb_get("suscripciones", f"usuario_id=eq.{user_id}")
    if not res:
        return True
    return not res[0].get("trial_usado", False)


def _payphone_activo():
    return bool(PP_TOKEN and PP_STORE_ID)


def _activar_premium(user_id, meses, metodo="payphone", referencia_pago="", monto=0.0):
    """Activa o extiende el plan premium y registra el pago."""
    hoy       = datetime.date.today()
    existente = sb_get("suscripciones", f"usuario_id=eq.{user_id}")

    if existente:
        fecha_actual = existente[0].get("fecha_fin")
        base = (datetime.date.fromisoformat(fecha_actual)
                if fecha_actual and fecha_actual > str(hoy) else hoy)
        nueva_fecha = base + datetime.timedelta(days=30 * meses)
        sb_patch("suscripciones", f"usuario_id=eq.{user_id}", {
            "plan":          "premium",
            "activa":        True,
            "fecha_inicio":  str(hoy),
            "fecha_fin":     str(nueva_fecha),
            "metodo_pago":   metodo,
        })
    else:
        nueva_fecha = hoy + datetime.timedelta(days=30 * meses)
        sb_post("suscripciones", {
            "usuario_id":   user_id,
            "plan":         "premium",
            "activa":       True,
            "fecha_inicio": str(hoy),
            "fecha_fin":    str(nueva_fecha),
            "metodo_pago":  metodo,
        })

    if monto > 0 or referencia_pago:
        sb_post("pagos", {
            "usuario_id":        user_id,
            "stripe_payment_id": referencia_pago or None,
            "monto":             monto,
            "meses":             meses,
            "estado":            "completado",
            "metodo":            metodo,
        })

    return nueva_fecha


# ── Vista de planes ────────────────────────────────────────────────────────────

@bp.route("/planes")
def planes():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _  = get_granja_info(session["user_id"])
    premium      = es_premium_owner(session["user_id"])
    dias         = dias_restantes(owner_id)
    sus_actual   = sb_get("suscripciones", f"usuario_id=eq.{owner_id}")
    trial_ok     = tiene_trial_disponible(owner_id)

    return render_template(
        "planes.html",
        es_premium      = premium,
        dias_restantes  = dias,
        suscripcion     = sus_actual[0] if sus_actual else None,
        planes          = PLANES,
        trial_ok        = trial_ok,
        dias_trial      = DIAS_TRIAL,
        payphone_activo = _payphone_activo(),
    )


# ── Trial gratuito ─────────────────────────────────────────────────────────────

@bp.route("/activar_trial", methods=["POST"])
def activar_trial():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    if not tiene_trial_disponible(owner_id):
        flash("Ya usaste tu periodo de prueba gratuito.", "error")
        return redirect("/planes")

    if es_premium_owner(session["user_id"]):
        flash("Ya tienes un plan activo.", "error")
        return redirect("/planes")

    trial_fin = datetime.date.today() + datetime.timedelta(days=DIAS_TRIAL)
    existente = sb_get("suscripciones", f"usuario_id=eq.{owner_id}")
    datos = {
        "plan":         "premium",
        "activa":       True,
        "fecha_inicio": str(datetime.date.today()),
        "fecha_fin":    str(trial_fin),
        "metodo_pago":  "trial",
        "trial_usado":  True,
    }
    if existente:
        sb_patch("suscripciones", f"usuario_id=eq.{owner_id}", datos)
    else:
        sb_post("suscripciones", {"usuario_id": owner_id, **datos})

    flash(f"Tus {DIAS_TRIAL} dias de prueba gratuita fueron activados. Disfruta todas las funciones Premium.", "success")
    return redirect("/")


# ── Iniciar pago PayPhone ──────────────────────────────────────────────────────

@bp.route("/checkout/<meses>", methods=["POST"])
def checkout(meses):
    if "user_id" not in session:
        return redirect("/login")

    if meses not in PLANES:
        flash("Plan invalido.", "error")
        return redirect("/planes")

    if not _payphone_activo():
        flash("El sistema de pago no esta configurado aun. "
              "Escribenos por WhatsApp para activar tu plan.", "error")
        return redirect("/planes")

    owner_id, _ = get_granja_info(session["user_id"])
    plan        = PLANES[meses]
    client_tx   = f"pecua-{owner_id}-{meses}m-{int(datetime.datetime.now().timestamp())}"

    payload = {
        "amount":              plan["precio_ctvs"],
        "amountWithoutTax":    plan["precio_ctvs"],
        "amountWithTax":       0,
        "tax":                 0,
        "service":             0,
        "tip":                 0,
        "currency":            "USD",
        "storeId":             PP_STORE_ID,
        "clientTransactionId": client_tx,
        "responseUrl":         f"{APP_URL}/pago_resultado",
        "cancellationUrl":     f"{APP_URL}/planes",
        "lang":                "es",
        "reference":           f"Premium {plan['label']} - ERP Pecuario",
        "documentId":          str(owner_id),
    }

    try:
        res  = http.post(
            f"{PP_API_URL}/button/Prepare",
            json    = payload,
            headers = {
                "Authorization": f"Bearer {PP_TOKEN}",
                "Content-Type":  "application/json",
            },
            timeout = (5, 15),
        )
        data = res.json()
    except Exception as e:
        flash(f"Error al conectar con PayPhone: {e}", "error")
        return redirect("/planes")

    pay_url = data.get("url", "")
    if res.status_code != 200 or not pay_url:
        msg = data.get("message") or data.get("error") or str(data)
        flash(f"PayPhone error: {msg}", "error")
        return redirect("/planes")

    session["pp_tx"]    = client_tx
    session["pp_meses"] = meses
    session["pp_monto"] = plan["precio_usd"]

    return redirect(pay_url, code=303)


# ── Resultado del pago (retorno de PayPhone) ──────────────────────────────────

@bp.route("/pago_resultado")
def pago_resultado():
    if "user_id" not in session:
        return redirect("/login")

    client_tx = request.args.get("clientTransactionId", "")
    pp_id     = request.args.get("id", "")
    status    = request.args.get("status", "").lower()

    owner_id, _ = get_granja_info(session["user_id"])
    meses = session.pop("pp_meses", "1")
    monto = session.pop("pp_monto", 0.0)
    session.pop("pp_tx", None)

    if status in ("cancel", "failed", "rejected"):
        flash("Pago cancelado o rechazado. Puedes intentarlo nuevamente.", "error")
        return redirect("/planes")

    verificado = False
    if pp_id and PP_TOKEN:
        try:
            ver = http.get(
                f"{PP_API_URL}/button/V2/Confirm"
                f"?id={pp_id}&clientTransactionId={client_tx}",
                headers = {"Authorization": f"Bearer {PP_TOKEN}"},
                timeout = (5, 10),
            )
            ver_data  = ver.json()
            tx_status = ver_data.get("transactionStatus", "")
            verificado = (tx_status == "Approved")

            if tx_status in ("Canceled", "Reversed", "Refunded"):
                flash("El pago fue cancelado o revertido por el banco.", "error")
                return redirect("/planes")

        except Exception as e:
            print(f"Error verificando PayPhone: {e}")

    if verificado or status in ("approved", "ok"):
        nueva_fecha = _activar_premium(
            owner_id,
            meses           = int(meses),
            metodo          = "payphone",
            referencia_pago = pp_id or client_tx,
            monto           = float(monto),
        )
        plan = PLANES.get(meses, {})
        flash(f"Plan {plan.get('label','Premium')} activado hasta el "
              f"{nueva_fecha.strftime('%d/%m/%Y')}. Bienvenido.", "success")
        return redirect("/")

    flash("No se pudo confirmar el pago. Si fue cobrado, "
          "contactanos por WhatsApp y lo activamos manualmente.", "error")
    return redirect("/planes")


# ── Cancelar al vencer ────────────────────────────────────────────────────────

@bp.route("/cancelar_premium", methods=["POST"])
def cancelar_premium():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    sb_patch("suscripciones", f"usuario_id=eq.{owner_id}",
             {"cancelar_al_vencer": True})
    flash("Plan marcado para cancelar al vencer. "
          "Sigues con acceso hasta la fecha de expiracion.", "info")
    return redirect("/planes")


# ── Historial de pagos ────────────────────────────────────────────────────────

@bp.route("/mis_pagos")
def mis_pagos():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    pagos = sb_get("pagos", f"usuario_id=eq.{owner_id}&order=fecha.desc")
    return render_template("mis_pagos.html", pagos=pagos)