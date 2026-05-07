# routes/bajas.py
"""
Módulo de Bajas de Animales — ERP Pecuario
Registra muertes, robos, descartes y donaciones que reducen el inventario
sin generar un ingreso de venta.
"""
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin

bp = Blueprint("bajas", __name__)


# Tipos de baja con emoji y etiqueta
TIPOS_BAJA = {
    "muerte":   {"label": "Muerte",            "emoji": "💀", "color": "#e74c3c"},
    "robo":     {"label": "Robo / Extravío",   "emoji": "🚨", "color": "#8e44ad"},
    "descarte": {"label": "Descarte sanitario","emoji": "🚫", "color": "#e67e22"},
    "donacion": {"label": "Donación",          "emoji": "🤝", "color": "#3498db"},
}


def _fmt(valor):
    return round(float(valor or 0), 2)


# ================= VISTA PRINCIPAL =================
@bp.route("/bajas")
def bajas():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])

    # Lotes activos para el formulario
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.true")

    # Todas las bajas con nombre de lote
    todas = sb_get("bajas", f"usuario_id=eq.{owner_id}&order=fecha.desc")
    todos_lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    lotes_idx   = {l["id"]: l["nombre"] for l in todos_lotes}

    for b in todas:
        b["lote_nombre"] = lotes_idx.get(b.get("lote_id"), "Desconocido")
        b["tipo_info"]   = TIPOS_BAJA.get(b.get("tipo", ""), {
            "label": b.get("tipo", ""), "emoji": "❓", "color": "#95a5a6"
        })

    # KPI: mortalidad del período (muertes / total inicial de lotes activos)
    total_inicial  = sum(l.get("cantidad_inicial", 0) for l in todos_lotes)
    total_muertes  = sum(b.get("cantidad", 0) for b in todas if b.get("tipo") == "muerte")
    pct_mortalidad = round((total_muertes / total_inicial * 100), 1) if total_inicial > 0 else 0

    return render_template(
        "bajas.html",
        lotes=lotes,
        bajas=todas,
        mi_rol=mi_rol,
        tipos=TIPOS_BAJA,
        total_muertes=total_muertes,
        pct_mortalidad=pct_mortalidad,
    )


# ================= REGISTRAR BAJA (operador y admin) =================
@bp.route("/registrar_baja", methods=["POST"])
def registrar_baja():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lote_id  = request.form.get("lote_id",  "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    tipo     = request.form.get("tipo",     "").strip()
    causa    = request.form.get("causa",    "").strip()
    fecha    = request.form.get("fecha",    "").strip()
    notas    = request.form.get("notas",    "").strip()

    # Validación básica
    if not all([lote_id, cantidad, tipo, fecha]):
        flash("Completa lote, cantidad, tipo y fecha.", "error")
        return redirect("/bajas")

    if tipo not in TIPOS_BAJA:
        flash("Tipo de baja inválido.", "error")
        return redirect("/bajas")

    try:
        lote_id  = int(lote_id)
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        flash("La cantidad debe ser un número entero positivo.", "error")
        return redirect("/bajas")

    # Verificar que el lote pertenece al dueño
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/bajas")

    disponibles = lote[0].get("cantidad_actual", 0)
    if cantidad > disponibles:
        flash(
            f"No puedes dar de baja {cantidad} animales. "
            f"El lote solo tiene {disponibles} disponibles.",
            "error"
        )
        return redirect("/bajas")

    backup_automatico(owner_id)

    # Registrar la baja
    sb_post("bajas", {
        "usuario_id": owner_id,
        "lote_id":    lote_id,
        "cantidad":   cantidad,
        "tipo":       tipo,
        "causa":      causa or None,
        "fecha":      fecha,
        "notas":      notas or None,
    })

    # Actualizar cantidad del lote
    nueva = disponibles - cantidad
    sb_patch(
        "lotes",
        f"id=eq.{lote_id}&usuario_id=eq.{owner_id}",
        {"cantidad_actual": nueva, "activo": nueva > 0},
    )

    tipo_label = TIPOS_BAJA[tipo]["label"]
    flash(
        f"✅ Baja de {cantidad} animales registrada ({tipo_label}). "
        f"Quedan {nueva} en el lote.",
        "success"
    )
    return redirect("/bajas")


# ================= ELIMINAR BAJA (solo admin — devuelve animales al lote) =================
@bp.route("/eliminar_baja/<baja_id>", methods=["POST"])
@solo_admin
def eliminar_baja(baja_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    baja = sb_get("bajas", f"id=eq.{baja_id}&usuario_id=eq.{owner_id}")
    if not baja:
        flash("Registro no encontrado.", "error")
        return redirect("/bajas")

    b = baja[0]
    backup_automatico(owner_id)

    # Devolver animales al lote
    lote = sb_get("lotes", f"id=eq.{b['lote_id']}&usuario_id=eq.{owner_id}")
    if lote:
        nueva_cantidad = lote[0].get("cantidad_actual", 0) + b.get("cantidad", 0)
        sb_patch(
            "lotes",
            f"id=eq.{b['lote_id']}&usuario_id=eq.{owner_id}",
            {"cantidad_actual": nueva_cantidad, "activo": True},
        )

    sb_delete("bajas", f"id=eq.{baja_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Registro eliminado y animales devueltos al lote.", "success")
    return redirect("/bajas")


# ================= API: resumen de bajas por lote =================
@bp.route("/api/bajas_resumen/<lote_id>")
def api_bajas_resumen(lote_id):
    """Retorna totales de bajas por tipo para un lote específico."""
    if "user_id" not in session:
        return jsonify({})

    owner_id, _ = get_granja_info(session["user_id"])
    bajas = sb_get("bajas", f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}")

    resumen = {}
    for b in bajas:
        t = b.get("tipo", "otro")
        resumen[t] = resumen.get(t, 0) + b.get("cantidad", 0)

    return jsonify(resumen)