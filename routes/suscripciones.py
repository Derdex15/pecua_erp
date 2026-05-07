from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch
import datetime

bp = Blueprint("suscripciones", __name__)


def es_premium(user_id):
    hoy = str(datetime.date.today())
    res = sb_get("suscripciones",
                 f"usuario_id=eq.{user_id}&plan=eq.premium&activa=eq.true&fecha_fin=gte.{hoy}")
    return bool(res)


def dias_restantes(user_id):
    """Retorna días restantes del plan premium, o 0 si no tiene."""
    hoy = str(datetime.date.today())
    res = sb_get("suscripciones",
                 f"usuario_id=eq.{user_id}&plan=eq.premium&activa=eq.true&fecha_fin=gte.{hoy}")
    if not res:
        return 0
    fecha_fin = datetime.date.fromisoformat(res[0]["fecha_fin"])
    return (fecha_fin - datetime.date.today()).days


# ================= VISTA DE PLANES =================
@bp.route("/planes")
def planes():
    if "user_id" not in session:
        return redirect("/login")

    user_id   = session["user_id"]
    premium   = es_premium(user_id)
    dias      = dias_restantes(user_id)
    sus_actual = sb_get("suscripciones", f"usuario_id=eq.{user_id}")

    return render_template("planes.html",
                           es_premium=premium,
                           dias_restantes=dias,
                           suscripcion=sus_actual[0] if sus_actual else None)


# ================= ACTIVAR PREMIUM (simulado — sin pasarela de pago aún) =================
@bp.route("/activar_premium", methods=["POST"])
def activar_premium():
    """
    En producción este endpoint se llama después de confirmar el pago
    desde la pasarela (Stripe, PayPal, etc.).
    Por ahora activa manualmente para pruebas — reemplazar con webhook de pago.
    """
    if "user_id" not in session:
        return redirect("/login")

    user_id   = session["user_id"]
    meses     = int(request.form.get("meses", 1))

    hoy       = datetime.date.today()
    fecha_fin = hoy + datetime.timedelta(days=30 * meses)

    existente = sb_get("suscripciones", f"usuario_id=eq.{user_id}")

    if existente:
        # Si ya tiene suscripción, extender la fecha
        fecha_actual = existente[0].get("fecha_fin")
        if fecha_actual and fecha_actual > str(hoy):
            # Extender desde la fecha actual de vencimiento
            base = datetime.date.fromisoformat(fecha_actual)
        else:
            base = hoy
        nueva_fecha = base + datetime.timedelta(days=30 * meses)

        sb_patch("suscripciones", f"usuario_id=eq.{user_id}", {
            "plan":        "premium",
            "activa":      True,
            "fecha_inicio": str(hoy),
            "fecha_fin":   str(nueva_fecha),
        })
    else:
        sb_post("suscripciones", {
            "usuario_id":  user_id,
            "plan":        "premium",
            "activa":      True,
            "fecha_inicio": str(hoy),
            "fecha_fin":   str(fecha_fin),
        })

    flash(f"🌟 ¡Premium activado hasta el {fecha_fin.strftime('%d/%m/%Y')}!", "success")
    return redirect("/planes")


# ================= CANCELAR PREMIUM =================
@bp.route("/cancelar_premium", methods=["POST"])
def cancelar_premium():
    if "user_id" not in session:
        return redirect("/login")

    sb_patch("suscripciones", f"usuario_id=eq.{session['user_id']}", {
        "activa": False
    })
    flash("Plan cancelado. Tus datos se mantienen seguros.", "info")
    return redirect("/planes")