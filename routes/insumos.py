# routes/insumos.py
"""
Inventario de Insumos — ERP Pecuario
Controla el stock físico: alimento, medicamentos, vacunas, equipos.
Genera alertas cuando el stock cae por debajo del mínimo configurado.
"""
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from routes.permisos import get_granja_info, solo_admin
import datetime

bp = Blueprint("insumos", __name__)

CATEGORIAS = {
    "alimento":      {"label": "Alimento",      "emoji": "🌽", "color": "#f39c12"},
    "medicamento":   {"label": "Medicamento",   "emoji": "💊", "color": "#e74c3c"},
    "vacuna":        {"label": "Vacuna",         "emoji": "💉", "color": "#3498db"},
    "equipo":        {"label": "Equipo",         "emoji": "🔧", "color": "#95a5a6"},
    "desinfectante": {"label": "Desinfectante",  "emoji": "🧴", "color": "#9b59b6"},
    "otro":          {"label": "Otro",           "emoji": "📦", "color": "#7f8c8d"},
}


def _fmt(v):
    return round(float(v or 0), 2)


def _generar_alertas_stock(owner_id, insumo):
    """Crea alerta si el stock del insumo está en o por debajo del mínimo."""
    if insumo.get("stock_min") is None:
        return
    if _fmt(insumo["cantidad"]) <= _fmt(insumo["stock_min"]):
        hoy = str(datetime.date.today())
        existente = sb_get("alertas",
                           f"usuario_id=eq.{owner_id}"
                           f"&tipo=eq.stock_insumo"
                           f"&fecha_alerta=eq.{hoy}"
                           f"&mensaje=ilike.*{insumo['id']}*")
        if not existente:
            sb_post("alertas", {
                "usuario_id":   owner_id,
                "lote_id":      None,
                "tipo":         "stock_insumo",
                "mensaje":      f"⚠️ Stock bajo: {insumo['nombre']} — "
                                f"{_fmt(insumo['cantidad'])} {insumo['unidad']} "
                                f"(mínimo: {_fmt(insumo['stock_min'])}) [id:{insumo['id']}]",
                "fecha_alerta": hoy,
                "leida":        False,
            })


# ── LISTA ─────────────────────────────────────────────────────
@bp.route("/insumos")
def insumos():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    if not es_premium_owner(session["user_id"]):
        return render_template("premium_requerido.html", funcion="Inventario de Insumos")
    filtro_cat = request.args.get("categoria", "")

    q = f"usuario_id=eq.{owner_id}&order=nombre.asc"
    if filtro_cat:
        q += f"&categoria=eq.{filtro_cat}"

    todos = sb_get("insumos", q)

    for ins in todos:
        ins["categoria_info"] = CATEGORIAS.get(ins.get("categoria","otro"), CATEGORIAS["otro"])
        ins["cantidad"]       = _fmt(ins.get("cantidad", 0))
        ins["stock_min"]      = _fmt(ins.get("stock_min", 0))
        ins["bajo_stock"]     = ins["cantidad"] <= ins["stock_min"] and ins["stock_min"] > 0

        # Generar alerta si aplica
        if ins["bajo_stock"]:
            _generar_alertas_stock(owner_id, ins)

    # KPIs
    total_items     = len(todos)
    items_bajo_stk  = sum(1 for i in todos if i["bajo_stock"])

    return render_template("insumos.html",
        insumos=todos, mi_rol=mi_rol,
        categorias=CATEGORIAS, filtro_cat=filtro_cat,
        total_items=total_items, items_bajo_stk=items_bajo_stk)


# ── CREAR ─────────────────────────────────────────────────────
@bp.route("/crear_insumo", methods=["POST"])
@solo_admin
def crear_insumo():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    nombre    = request.form.get("nombre",    "").strip()
    categoria = request.form.get("categoria", "otro").strip()
    cantidad  = request.form.get("cantidad",  "0").strip()
    unidad    = request.form.get("unidad",    "").strip()
    stock_min = request.form.get("stock_min", "0").strip()
    proveedor = request.form.get("proveedor", "").strip() or None
    notas     = request.form.get("notas",     "").strip() or None

    if not all([nombre, unidad]):
        flash("Nombre y unidad son obligatorios.", "error")
        return redirect("/insumos")
    if categoria not in CATEGORIAS:
        flash("Categoría inválida.", "error")
        return redirect("/insumos")

    try:
        cantidad  = round(float(cantidad), 2)
        stock_min = round(float(stock_min), 2)
        if cantidad < 0 or stock_min < 0:
            raise ValueError
    except ValueError:
        flash("Cantidad y stock mínimo deben ser números positivos.", "error")
        return redirect("/insumos")

    sb_post("insumos", {
        "usuario_id": owner_id, "nombre": nombre,
        "categoria": categoria, "cantidad": cantidad,
        "unidad": unidad, "stock_min": stock_min,
        "proveedor": proveedor, "notas": notas,
    })
    flash(f"✅ '{nombre}' agregado al inventario.", "success")
    return redirect("/insumos")


# ── AJUSTAR STOCK (entrada/salida de mercancía) ────────────────
@bp.route("/ajustar_insumo/<insumo_id>", methods=["POST"])
def ajustar_insumo(insumo_id):
    """
    Suma o resta cantidad al stock actual.
    Operación: '+' para entrada, '-' para salida/consumo.
    """
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    ins = sb_get("insumos", f"id=eq.{insumo_id}&usuario_id=eq.{owner_id}")
    if not ins:
        flash("Insumo no encontrado.", "error")
        return redirect("/insumos")

    operacion = request.form.get("operacion", "+").strip()
    ajuste    = request.form.get("ajuste",    "0").strip()

    try:
        ajuste = round(float(ajuste), 2)
        if ajuste <= 0:
            raise ValueError
    except ValueError:
        flash("La cantidad de ajuste debe ser un número positivo.", "error")
        return redirect("/insumos")

    actual = _fmt(ins[0].get("cantidad", 0))
    if operacion == "-":
        nueva = actual - ajuste
        if nueva < 0:
            flash(f"No hay suficiente stock. Disponible: {actual} {ins[0].get('unidad','')}", "error")
            return redirect("/insumos")
    else:
        nueva = actual + ajuste

    nueva = round(nueva, 2)
    sb_patch("insumos", f"id=eq.{insumo_id}&usuario_id=eq.{owner_id}", {
        "cantidad":   nueva,
        "updated_at": str(datetime.datetime.utcnow()),
    })

    ins[0]["cantidad"] = nueva
    _generar_alertas_stock(owner_id, ins[0])

    op_label = "➕ entrada" if operacion == "+" else "➖ salida"
    flash(f"✅ {op_label} de {ajuste} registrada. Stock actual: {nueva} {ins[0].get('unidad','')}", "success")
    return redirect("/insumos")


# ── EDITAR (solo admin) ────────────────────────────────────────
@bp.route("/editar_insumo/<insumo_id>", methods=["POST"])
@solo_admin
def editar_insumo(insumo_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    if not sb_get("insumos", f"id=eq.{insumo_id}&usuario_id=eq.{owner_id}"):
        flash("Insumo no encontrado.", "error")
        return redirect("/insumos")

    nombre    = request.form.get("nombre",    "").strip()
    stock_min = request.form.get("stock_min", "0").strip()
    proveedor = request.form.get("proveedor", "").strip() or None
    notas     = request.form.get("notas",     "").strip() or None

    try:
        stock_min = round(float(stock_min), 2)
    except ValueError:
        flash("Stock mínimo inválido.", "error")
        return redirect("/insumos")

    sb_patch("insumos", f"id=eq.{insumo_id}&usuario_id=eq.{owner_id}", {
        "nombre": nombre, "stock_min": stock_min,
        "proveedor": proveedor, "notas": notas,
    })
    flash(f"✅ '{nombre}' actualizado.", "success")
    return redirect("/insumos")


# ── ELIMINAR (solo admin) ──────────────────────────────────────
@bp.route("/eliminar_insumo/<insumo_id>", methods=["POST"])
@solo_admin
def eliminar_insumo(insumo_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    ins = sb_get("insumos", f"id=eq.{insumo_id}&usuario_id=eq.{owner_id}")
    if not ins:
        flash("Insumo no encontrado.", "error")
        return redirect("/insumos")

    sb_delete("insumos", f"id=eq.{insumo_id}&usuario_id=eq.{owner_id}")
    flash(f"🗑 '{ins[0].get('nombre','')}' eliminado.", "success")
    return redirect("/insumos")