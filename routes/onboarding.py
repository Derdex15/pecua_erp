# routes/onboarding.py
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post
from routes.permisos import get_granja_info

bp = Blueprint("onboarding", __name__)


@bp.route("/onboarding")
def onboarding():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, rol = get_granja_info(session["user_id"])

    try:
        paso = int(request.args.get("paso", 1))
    except (ValueError, TypeError):
        paso = 1

    if paso not in (1, 2, 3):
        paso = 1

    # Operadores no pueden crear lotes en paso 2
    if rol != "admin" and paso == 2:
        flash("Solo el administrador puede crear lotes.", "info")
        return redirect("/")

    # CORRECCIÓN: el paso=3 es la pantalla de éxito DESPUÉS de crear el lote.
    # Si llegamos aquí con paso=3, siempre mostrarlo aunque ya haya lotes.
    if paso == 3:
        return render_template("onboarding.html",
                               paso=3,
                               username=session.get("username", ""))

    # Pasos 1 y 2: si el usuario ya tiene lotes y no solicita revisar la guía, ir al dashboard
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    if lotes and not request.args.get("guia"):
        return redirect("/")

    return render_template("onboarding.html",
                           paso=paso,
                           username=session.get("username", ""))


@bp.route("/onboarding/crear_lote", methods=["POST"])
def onboarding_crear_lote():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, rol = get_granja_info(session["user_id"])
    if rol != "admin":
        flash("Solo el administrador puede crear lotes.", "error")
        return redirect("/")

    nombre   = request.form.get("nombre",   "").strip()
    tipo     = request.form.get("tipo",     "").strip()
    raza     = request.form.get("raza",     "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo",    "0").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([nombre, tipo, raza, cantidad, fecha]):
        flash("Completa todos los campos obligatorios para continuar.", "error")
        return render_template("onboarding.html",
                               paso=2,
                               username=session.get("username", ""),
                               form_data=request.form)

    try:
        cant_num  = int(cantidad)
        costo_num = round(float(costo or 0), 2)
        if cant_num <= 0 or costo_num < 0:
            raise ValueError
    except ValueError:
        flash("Cantidad debe ser entero positivo y el costo un número válido.", "error")
        return render_template("onboarding.html",
                               paso=2,
                               username=session.get("username", ""),
                               form_data=request.form)

    res = sb_post("lotes", {
        "usuario_id":       owner_id,
        "nombre":           nombre,
        "tipo":             tipo,
        "raza":             raza,
        "cantidad_inicial": cant_num,
        "cantidad_actual":  cant_num,
        "costo_compra":     costo_num,
        "fecha":            fecha,
        "activo":           True,
    })

    # Verificar si la inserción fue exitosa
    es_ok = getattr(res, "ok", False) or getattr(res, "status_code", 0) in (200, 201)
    if not es_ok:
        flash("Error de conexión al guardar el lote. Por favor intenta de nuevo.", "error")
        return render_template("onboarding.html",
                               paso=2,
                               username=session.get("username", ""),
                               form_data=request.form)

    # Redirige a paso=3 — la ruta ahora siempre lo muestra sin importar si hay lotes
    return redirect("/onboarding?paso=3")


@bp.route("/onboarding/saltar")
def onboarding_saltar():
    return redirect("/")
