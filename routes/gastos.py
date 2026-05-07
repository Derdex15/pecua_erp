# routes/gastos.py
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin

bp = Blueprint("gastos", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ================= VISTA GASTOS =================
@bp.route("/gastos")
def gastos():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])

    # Lotes activos del dueño para el formulario
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.true")

    # Gastos del dueño con nombre de lote
    todos_gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}&order=fecha.desc")
    todos_lotes  = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    lotes_idx    = {l["id"]: l["nombre"] for l in todos_lotes}

    for g in todos_gastos:
        g["lote_nombre"] = lotes_idx.get(g.get("lote_id"), "Desconocido")
        g["costo"]       = _fmt(g.get("costo", 0))

    return render_template("gastos.html", lotes=lotes, gastos=todos_gastos, mi_rol=mi_rol)


# ================= AGREGAR GASTO (operador y admin) =================
@bp.route("/agregar_gasto", methods=["POST"])
def agregar_gasto():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lote_id  = request.form.get("lote_id",  "").strip()
    nombre   = request.form.get("nombre",   "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo",    "").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([lote_id, nombre, costo, fecha]):
        flash("Completa todos los campos obligatorios.", "error")
        return redirect("/gastos")

    try:
        lote_id = int(lote_id)
        costo   = round(float(costo), 2)
        if costo < 0:
            raise ValueError
    except ValueError:
        flash("Lote o costo inválido.", "error")
        return redirect("/gastos")

    # Validar que el lote pertenece al dueño
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/gastos")

    backup_automatico(owner_id)

    sb_post("gastos", {
        "usuario_id": owner_id,   # ← siempre del dueño
        "lote_id":    lote_id,
        "nombre":     nombre,
        "cantidad":   cantidad,
        "costo":      costo,
        "fecha":      fecha,
    })

    flash(f"✅ Gasto '{nombre}' registrado correctamente.", "success")
    return redirect("/gastos")


# ================= EDITAR GASTO (solo admin) =================
@bp.route("/editar_gasto/<gasto_id>")
@solo_admin
def editar_gasto(gasto_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    gasto = sb_get("gastos", f"id=eq.{gasto_id}&usuario_id=eq.{owner_id}")
    if not gasto:
        flash("Gasto no encontrado.", "error")
        return redirect("/gastos")

    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    return render_template("editar_gasto.html", gasto=gasto[0], lotes=lotes)


# ================= GUARDAR GASTO EDITADO (solo admin) =================
@bp.route("/guardar_gasto/<gasto_id>", methods=["POST"])
@solo_admin
def guardar_gasto(gasto_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    gasto = sb_get("gastos", f"id=eq.{gasto_id}&usuario_id=eq.{owner_id}")
    if not gasto:
        flash("Gasto no encontrado.", "error")
        return redirect("/gastos")

    nombre   = request.form.get("nombre",   "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo",    "").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([nombre, costo, fecha]):
        flash("Nombre, costo y fecha son obligatorios.", "error")
        return redirect(f"/editar_gasto/{gasto_id}")

    try:
        costo = round(float(costo), 2)
        if costo < 0:
            raise ValueError
    except ValueError:
        flash("El costo debe ser un número válido.", "error")
        return redirect(f"/editar_gasto/{gasto_id}")

    sb_patch(
        "gastos",
        f"id=eq.{gasto_id}&usuario_id=eq.{owner_id}",
        {"nombre": nombre, "cantidad": cantidad, "costo": costo, "fecha": fecha},
    )

    flash(f"✅ Gasto '{nombre}' actualizado.", "success")
    return redirect("/gastos")


# ================= ELIMINAR GASTO (solo admin) =================
@bp.route("/eliminar_gasto/<gasto_id>", methods=["POST"])
@solo_admin
def eliminar_gasto(gasto_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    gasto = sb_get("gastos", f"id=eq.{gasto_id}&usuario_id=eq.{owner_id}")
    if not gasto:
        flash("Gasto no encontrado.", "error")
        return redirect("/gastos")

    backup_automatico(owner_id)
    sb_delete("gastos", f"id=eq.{gasto_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Gasto eliminado.", "success")
    return redirect("/gastos")