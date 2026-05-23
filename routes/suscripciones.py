# routes/suscripciones.py
"""
Suscripciones y Pagos — ERP Pecuario
Pasarela: PayPhone (Ecuador)

Variables de entorno necesarias en Render:
  PAYPHONE_TOKEN    -> Token de tu cuenta PayPhone
  PAYPHONE_STORE_ID -> ID del Store en PayPhone
  APP_URL           -> https://erpecuario.com
"""
import os
import datetime
import requests as http
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch
from routes.permisos import get_granja_info, es_premium_owner, login_required

bp = Blueprint("suscripciones", __name__)

APP_URL     = os.getenv("APP_URL", "https://erpecuario.com")
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
            "plan":         "premium",
            "activa":       True,
            "fecha_inicio": str(hoy),
            "fecha_fin":    str(nueva_fecha),
            "metodo_pago":  metodo,
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
            "referencia_pago":   referencia_pago or None,
            "monto":             monto,
            "meses":             meses,
            "estado":            "completado",
            "metodo":            metodo,
        })

    return nueva_fecha


def _registrar_pago_pendiente(user_id, meses, referencia_pago, monto):
    """Registra un pago que no pudo verificarse para revisión manual."""
    sb_post("pagos", {
        "usuario_id":      user_id,
        "referencia_pago": referencia_pago or None,
        "monto":           monto,
        "meses":           meses,
        "estado":          "pendiente_verificacion",
        "metodo":          "payphone",
    })


# ── Vista de planes ────────────────────────────────────────────────────────────

@bp.route("/planes")
@login_required
def planes():
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
@login_required
def activar_trial():
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

    flash(f"Tus {DIAS_TRIAL} días de prueba gratuita fueron activados. "
          "Disfruta todas las funciones Premium.", "success")
    return redirect("/")


# ── Iniciar pago PayPhone ──────────────────────────────────────────────────────

@bp.route("/checkout/<meses>", methods=["POST"])
@login_required
def checkout(meses):
    if meses not in PLANES:
        flash("Plan inválido.", "error")
        return redirect("/planes")

    if not _payphone_activo():
        flash("El sistema de pago no está configurado aún. "
              "Escríbenos por WhatsApp para activar tu plan.", "error")
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

    # Guardar en sesión para validar el retorno
    session["pp_tx"]    = client_tx
    session["pp_meses"] = meses
    session["pp_monto"] = plan["precio_usd"]
    session["pp_owner"] = owner_id   # ← validar que sea el mismo usuario al volver

    return redirect(pay_url, code=303)


# ── Resultado del pago (retorno de PayPhone) ──────────────────────────────────

@bp.route("/pago_resultado")
@login_required
def pago_resultado():
    client_tx_url = request.args.get("clientTransactionId", "")
    pp_id         = request.args.get("id", "")
    status        = request.args.get("status", "").lower()

    # Recuperar y limpiar datos de sesión
    client_tx_ses = session.pop("pp_tx",    None)
    meses         = session.pop("pp_meses", None)
    monto         = session.pop("pp_monto", 0.0)
    pp_owner      = session.pop("pp_owner", None)

    owner_id, _ = get_granja_info(session["user_id"])

    # ── Guardia 1: cancelación explícita ─────────────────────────────────────
    if status in ("cancel", "failed", "rejected"):
        flash("Pago cancelado o rechazado. Puedes intentarlo nuevamente.", "error")
        return redirect("/planes")

    # ── Guardia 2: validar que el retorno corresponde a ESTA sesión ──────────
    # Sin datos de sesión = la sesión expiró o la URL fue manipulada
    if not client_tx_ses or not meses:
        print(f"[PAGO] Sin datos de sesión al volver de PayPhone — "
              f"url_tx={client_tx_url} pp_id={pp_id}")
        flash("La sesión de pago expiró. Si fuiste cobrado, "
              "contáctanos por WhatsApp y lo activamos manualmente.", "error")
        return redirect("/planes")

    # El clientTransactionId de la URL debe coincidir con el de la sesión
    if client_tx_url != client_tx_ses:
        print(f"[PAGO SOSPECHOSO] tx_url={client_tx_url} != tx_ses={client_tx_ses} "
              f"user={session.get('user_id')} pp_id={pp_id}")
        flash("Error de validación del pago. "
              "Si fuiste cobrado, contáctanos y lo verificamos.", "error")
        return redirect("/planes")

    # El owner no debe haber cambiado entre checkout y retorno
    if pp_owner and pp_owner != owner_id:
        print(f"[PAGO SOSPECHOSO] owner_sesion={pp_owner} != owner_actual={owner_id}")
        flash("Error de validación. Contacta soporte.", "error")
        return redirect("/planes")

    # ── Guardia 3: verificar con la API de PayPhone (única fuente de verdad) ─
    verificado  = False
    tx_status   = ""
    ver_data    = {}

    if pp_id and PP_TOKEN:
        try:
            ver = http.get(
                f"{PP_API_URL}/button/V2/Confirm"
                f"?id={pp_id}&clientTransactionId={client_tx_ses}",
                headers = {"Authorization": f"Bearer {PP_TOKEN}"},
                timeout = (5, 10),
            )
            ver_data  = ver.json()
            tx_status = ver_data.get("transactionStatus", "")
            verificado = (tx_status == "Approved")

        except Exception as e:
            print(f"[PAGO] Error verificando con PayPhone: {e}")
            # Registrar como pendiente para revisión manual
            _registrar_pago_pendiente(owner_id, int(meses), pp_id or client_tx_ses, float(monto))
            flash("No pudimos verificar tu pago en este momento. "
                  "Si fuiste cobrado, contáctanos por WhatsApp con tu número de transacción "
                  f"({pp_id}) y lo activamos manualmente.", "error")
            return redirect("/planes")

    # Transacciones revertidas o canceladas por el banco
    if tx_status in ("Canceled", "Reversed", "Refunded"):
        flash("El pago fue cancelado o revertido por el banco.", "error")
        return redirect("/planes")

    # ── ÚNICO camino de activación: verificación exitosa con PayPhone ─────────
    if verificado:
        nueva_fecha = _activar_premium(
            owner_id,
            meses           = int(meses),
            metodo          = "payphone",
            referencia_pago = pp_id or client_tx_ses,
            monto           = float(monto),
        )
        plan = PLANES.get(meses, {})
        flash(f"¡Plan {plan.get('label','Premium')} activado hasta el "
              f"{nueva_fecha.strftime('%d/%m/%Y')}! Bienvenido a Premium.", "success")
        return redirect("/")

    # Verificación fallida sin error de red: pago no aprobado según PayPhone
    print(f"[PAGO] No verificado — tx_status={tx_status!r} "
          f"pp_id={pp_id} user={session.get('user_id')}")
    _registrar_pago_pendiente(owner_id, int(meses), pp_id or client_tx_ses, float(monto))
    flash("PayPhone no confirmó el pago. Si ves el cobro en tu banco, "
          "contáctanos por WhatsApp con tu número de transacción "
          f"({pp_id or client_tx_ses}) y lo activamos sin costo.", "error")
    return redirect("/planes")


# ── Cancelar al vencer ────────────────────────────────────────────────────────

@bp.route("/cancelar_premium", methods=["POST"])
@login_required
def cancelar_premium():
    owner_id, _ = get_granja_info(session["user_id"])
    sb_patch("suscripciones", f"usuario_id=eq.{owner_id}",
             {"cancelar_al_vencer": True})
    flash("Plan marcado para cancelar al vencer. "
          "Sigues con acceso hasta la fecha de expiración.", "info")
    return redirect("/planes")


# ── Historial de pagos ────────────────────────────────────────────────────────

@bp.route("/mis_pagos")
@login_required
def mis_pagos():
    owner_id, _ = get_granja_info(session["user_id"])
    pagos = sb_get("pagos", f"usuario_id=eq.{owner_id}&order=fecha.desc")
    return render_template("mis_pagos.html", pagos=pagos)