# routes/inventario.py
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin

bp = Blueprint("inventario", __name__)


def _fmt(valor):
    """Redondea a 2 decimales para evitar basura de punto flotante."""
    return round(float(valor or 0), 2)


# ================= DASHBOARD =================
@bp.route("/")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lotes  = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}")
    gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}")

    lotes_activos = [l for l in lotes if l.get("activo", True) and l.get("cantidad_actual", 0) > 0]

    total_animales = sum(l.get("cantidad_actual", 0) for l in lotes_activos)
    total_compra   = _fmt(sum(_fmt(l.get("costo_compra", 0)) for l in lotes))
    total_ventas   = _fmt(sum(_fmt(v.get("total", 0))        for v in ventas))
    total_gastos   = _fmt(sum(_fmt(g.get("costo", 0))        for g in gastos))
    inversion      = _fmt(total_compra + total_gastos)
    ganancia       = _fmt(total_ventas - inversion)

    detalle = {}
    for l in lotes_activos:
        tipo = l.get("tipo", "Desconocido")
        raza = l.get("raza", "Desconocido")
        detalle.setdefault(tipo, {})
        detalle[tipo][raza] = detalle[tipo].get(raza, 0) + l.get("cantidad_actual", 0)

    return render_template(
        "dashboard.html",
        total_animales=total_animales,
        detalle=detalle,
        ventas=total_ventas,
        inversion=inversion,
        ganancia=ganancia,
    )


# ================= INVENTARIO =================
@bp.route("/inventario")
def inventario():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.true")
    return render_template("inventario.html", lotes=lotes, mi_rol=mi_rol)


@bp.route("/lotes")
def lotes_redirect():
    return redirect("/inventario")


# ================= CREAR LOTE (solo admin) =================
@bp.route("/crear_lote", methods=["POST"])
@solo_admin
def crear_lote():
    if "user_id" not in session:
        return redirect("/login")

    # El owner_id es el del admin que hace la acción
    owner_id, _ = get_granja_info(session["user_id"])

    nombre   = request.form.get("nombre", "").strip()
    tipo     = request.form.get("tipo", "").strip()
    raza     = request.form.get("raza", "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo", "").strip()
    fecha    = request.form.get("fecha", "").strip()

    if not all([nombre, tipo, raza, cantidad, costo, fecha]):
        flash("Completa todos los campos del lote.", "error")
        return redirect("/inventario")
    try:
        cantidad = int(cantidad)
        costo    = round(float(costo), 2)
        if cantidad <= 0 or costo < 0:
            raise ValueError
    except ValueError:
        flash("Cantidad debe ser un entero positivo y costo un número válido.", "error")
        return redirect("/inventario")

    backup_automatico(owner_id)

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

    flash(f"✅ Lote '{nombre}' creado correctamente.", "success")
    return redirect("/inventario")


# ================= EDITAR LOTE (solo admin) =================
@bp.route("/editar_lote/<lote_id>")
@solo_admin
def editar_lote(lote_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/inventario")
    return render_template("editar_lote.html", lote=lote[0])


@bp.route("/guardar_lote/<lote_id>", methods=["POST"])
@solo_admin
def guardar_lote(lote_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/inventario")

    nombre = request.form.get("nombre", "").strip()
    costo  = request.form.get("costo", "").strip()
    fecha  = request.form.get("fecha", "").strip()

    if not all([nombre, costo, fecha]):
        flash("Nombre, costo y fecha son obligatorios.", "error")
        return redirect(f"/editar_lote/{lote_id}")
    try:
        costo = round(float(costo), 2)
        if costo < 0:
            raise ValueError
    except ValueError:
        flash("El costo debe ser un número válido.", "error")
        return redirect(f"/editar_lote/{lote_id}")

    sb_patch("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}", {
        "nombre": nombre, "costo_compra": costo, "fecha": fecha,
    })
    flash(f"✅ Lote '{nombre}' actualizado.", "success")
    return redirect("/inventario")


# ================= ELIMINAR LOTE (solo admin) =================
@bp.route("/eliminar_lote/<lote_id>", methods=["POST"])
@solo_admin
def eliminar_lote(lote_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/inventario")

    backup_automatico(owner_id)
    sb_delete("gastos", f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    sb_delete("ventas", f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    sb_delete("lotes",  f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")

    flash("🗑 Lote eliminado junto con sus ventas y gastos.", "success")
    return redirect("/inventario")


# ================= LOTES HISTORIAL =================
@bp.route("/lotes_historial")
def lotes_historial():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.false")
    return render_template("lotes_historial.html", lotes=lotes)