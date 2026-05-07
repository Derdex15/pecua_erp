# routes/ventas.py
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin

bp = Blueprint("ventas", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ================= MOVIMIENTOS (vista) =================
@bp.route("/movimientos")
def movimientos():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])

    lotes  = sb_get("lotes",  f"usuario_id=eq.{owner_id}&activo=eq.true")
    ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}&order=fecha.desc")

    todos_lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    lotes_idx   = {l["id"]: l["nombre"] for l in todos_lotes}
    for v in ventas:
        v["lote_nombre"] = lotes_idx.get(v.get("lote_id"), "Desconocido")
        v["total"]       = _fmt(v.get("total", 0))

    return render_template("movimientos.html", lotes=lotes, ventas=ventas, mi_rol=mi_rol)


# ================= REGISTRAR VENTA (operador y admin) =================
@bp.route("/registrar_venta", methods=["POST"])
def registrar_venta():
    if "user_id" not in session:
        return redirect("/login")

    # Usar owner_id para que los datos queden en la cuenta del dueño
    owner_id, _ = get_granja_info(session["user_id"])

    lote_id  = request.form.get("lote_id",  "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    total    = request.form.get("total",    "").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([lote_id, cantidad, total, fecha]):
        flash("Completa todos los campos de la venta.", "error")
        return redirect("/movimientos")
    try:
        lote_id  = int(lote_id)
        cantidad = int(cantidad)
        total    = round(float(total), 2)
        if cantidad <= 0 or total < 0:
            raise ValueError
    except ValueError:
        flash("Cantidad y total deben ser números positivos.", "error")
        return redirect("/movimientos")

    lote_data = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote_data:
        flash("Lote no encontrado.", "error")
        return redirect("/movimientos")

    disponibles = lote_data[0].get("cantidad_actual", 0)
    if cantidad > disponibles:
        flash(f"No puedes vender {cantidad}. Solo hay {disponibles} disponibles.", "error")
        return redirect("/movimientos")

    backup_automatico(owner_id)

    sb_post("ventas", {
        "usuario_id": owner_id,   # ← siempre del dueño
        "lote_id":    lote_id,
        "cantidad":   cantidad,
        "total":      total,
        "fecha":      fecha,
    })

    nueva = disponibles - cantidad
    sb_patch("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}",
             {"cantidad_actual": nueva, "activo": nueva > 0})

    flash(f"✅ Venta de {cantidad} animales por ${total:.2f} registrada.", "success")
    return redirect("/movimientos")


# ================= ELIMINAR VENTA (solo admin) =================
@bp.route("/eliminar_venta/<venta_id>", methods=["POST"])
@solo_admin
def eliminar_venta(venta_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    venta = sb_get("ventas", f"id=eq.{venta_id}&usuario_id=eq.{owner_id}")
    if not venta:
        flash("Venta no encontrada.", "error")
        return redirect("/movimientos")

    v = venta[0]
    backup_automatico(owner_id)

    lote = sb_get("lotes", f"id=eq.{v['lote_id']}&usuario_id=eq.{owner_id}")
    if lote:
        nueva_cantidad = lote[0].get("cantidad_actual", 0) + v.get("cantidad", 0)
        sb_patch("lotes", f"id=eq.{v['lote_id']}&usuario_id=eq.{owner_id}", {
            "cantidad_actual": nueva_cantidad, "activo": True
        })

    sb_delete("ventas", f"id=eq.{venta_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Venta eliminada y animales devueltos al lote.", "success")
    return redirect("/movimientos")