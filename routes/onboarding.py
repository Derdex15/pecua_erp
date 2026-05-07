# routes/onboarding.py
"""
Onboarding — ERP Pecuario
Flujo de 3 pasos que guía al usuario nuevo a crear su primer lote en 60 segundos.
Solo se muestra si el usuario no tiene lotes aún.
"""
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post
from routes.permisos import get_granja_info

bp = Blueprint("onboarding", __name__)


@bp.route("/onboarding")
def onboarding():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    # Si ya tiene lotes, no mostrar onboarding — ir al dashboard
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    if lotes:
        return redirect("/")

    paso = int(request.args.get("paso", 1))
    return render_template("onboarding.html",
                           paso=paso,
                           username=session.get("username", ""))


@bp.route("/onboarding/crear_lote", methods=["POST"])
def onboarding_crear_lote():
    """Crea el primer lote desde el onboarding y redirige al paso 3."""
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    nombre   = request.form.get("nombre",   "").strip()
    tipo     = request.form.get("tipo",     "").strip()
    raza     = request.form.get("raza",     "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo",    "0").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([nombre, tipo, raza, cantidad, fecha]):
        flash("Completa todos los campos para continuar.", "error")
        return redirect("/onboarding?paso=2")

    try:
        cantidad = int(cantidad)
        costo    = round(float(costo), 2)
        if cantidad <= 0 or costo < 0:
            raise ValueError
    except ValueError:
        flash("Cantidad debe ser un número entero y el costo un número válido.", "error")
        return redirect("/onboarding?paso=2")

    sb_post("lotes", {
        "usuario_id":       owner_id,
        "nombre":           nombre,
        "tipo":             tipo,
        "raza":             raza,
        "cantidad_inicial": cantidad,
        "cantidad_actual":  cantidad,
        "costo_compra":     costo,
        "fecha":            fecha,
        "activo":           True,
    })

    return redirect("/onboarding?paso=3")


@bp.route("/onboarding/saltar")
def onboarding_saltar():
    """Permite al usuario saltarse el onboarding e ir directo al dashboard."""
    return redirect("/")