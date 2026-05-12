# routes/inventario.py
"""
Dashboard y gestión de lotes — ERP Pecuario

CORRECCIÓN: la versión anterior no calculaba ni pasaba al template:
  roi, pct_mortalidad, precio_prom_venta, total_bajas,
  ventas_mes, gastos_mes, insumos_criticos, mi_rol,
  costo_por_kg  (KPI conversión alimenticia simplificado)
"""
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin
import datetime

bp = Blueprint("inventario", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ═══════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════
@bp.route("/")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])

    # ── Datos base ────────────────────────────────────────────────────────────
    lotes  = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}")
    gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}")
    bajas  = sb_get("bajas",  f"usuario_id=eq.{owner_id}")

    lotes_activos  = [l for l in lotes if l.get("activo", True)]
    lotes_con_anim = [l for l in lotes_activos if l.get("cantidad_actual", 0) > 0]

    # ── KPIs financieros globales ─────────────────────────────────────────────
    total_animales  = sum(l.get("cantidad_actual", 0) for l in lotes_con_anim)
    total_compra    = _fmt(sum(_fmt(l.get("costo_compra", 0)) for l in lotes))
    total_ventas    = _fmt(sum(_fmt(v.get("total",  0))       for v in ventas))
    total_gastos_v  = _fmt(sum(_fmt(g.get("costo",  0))       for g in gastos))
    inversion       = _fmt(total_compra + total_gastos_v)
    ganancia        = _fmt(total_ventas - inversion)
    roi             = round((ganancia / inversion * 100), 1) if inversion > 0 else 0

    # ── KPI mortalidad ────────────────────────────────────────────────────────
    total_inicial   = sum(l.get("cantidad_inicial", 0) for l in lotes)
    total_muertes   = sum(b.get("cantidad", 0) for b in bajas if b.get("tipo") == "muerte")
    total_bajas     = sum(b.get("cantidad", 0) for b in bajas)
    pct_mortalidad  = round((total_muertes / total_inicial * 100), 1) if total_inicial > 0 else 0

    # ── KPI precio promedio de venta (por animal) ─────────────────────────────
    total_cab_vendidas = sum(_fmt(v.get("cantidad", 0)) for v in ventas)
    precio_prom_venta  = _fmt(total_ventas / total_cab_vendidas) if total_cab_vendidas > 0 else 0

    # ── KPI costo por kg ganado (conversión alimenticia simplificada) ─────────
    # Toma todos los pesajes de lote, calcula la ganancia total en kg,
    # y divide entre el total de gastos para obtener costo por kg ganado.
    costo_por_kg = None
    try:
        pesajes_lote = sb_get("pesajes",
                              f"usuario_id=eq.{owner_id}&lote_id=not.is.null&order=fecha.asc")
        if pesajes_lote and total_gastos_v > 0:
            # Agrupar por lote_id, tomar primer y último pesaje
            lote_pesajes: dict = {}
            for p in pesajes_lote:
                lid = p.get("lote_id")
                if lid:
                    lote_pesajes.setdefault(lid, []).append(_fmt(p.get("peso_kg", 0)))
            kg_ganados = sum(
                max(pesos) - min(pesos)
                for pesos in lote_pesajes.values()
                if len(pesos) >= 2 and (max(pesos) - min(pesos)) > 0
            )
            if kg_ganados > 0:
                costo_por_kg = round(total_gastos_v / kg_ganados, 2)
    except Exception:
        pass

    # ── Resumen del mes actual ────────────────────────────────────────────────
    hoy     = datetime.date.today()
    mes_str = hoy.strftime("%Y-%m")
    ventas_mes = _fmt(sum(
        _fmt(v.get("total", 0)) for v in ventas
        if str(v.get("fecha", "")).startswith(mes_str)
    ))
    gastos_mes = _fmt(sum(
        _fmt(g.get("costo", 0)) for g in gastos
        if str(g.get("fecha", "")).startswith(mes_str)
    ))

    # ── Insumos con stock crítico ─────────────────────────────────────────────
    insumos = sb_get("insumos", f"usuario_id=eq.{owner_id}")
    insumos_criticos = sum(
        1 for i in insumos
        if i.get("stock_min") is not None and
           _fmt(i.get("cantidad", 0)) <= _fmt(i.get("stock_min", 0))
    )

    # ── Desglose por especie ──────────────────────────────────────────────────
    detalle: dict = {}
    for l in lotes_con_anim:
        tipo = l.get("tipo", "Desconocido")
        raza = l.get("raza", "Desconocido")
        detalle.setdefault(tipo, {})
        detalle[tipo][raza] = detalle[tipo].get(raza, 0) + l.get("cantidad_actual", 0)

    return render_template(
        "dashboard.html",
        # Conteos
        total_animales    = total_animales,
        detalle           = detalle,
        # Financiero global
        total_ventas      = total_ventas,
        inversion         = inversion,
        ganancia          = ganancia,
        roi               = roi,
        # KPIs ganaderos
        pct_mortalidad    = pct_mortalidad,
        total_muertes     = total_muertes,
        total_bajas       = total_bajas,
        precio_prom_venta = precio_prom_venta,
        costo_por_kg      = costo_por_kg,
        # Mes actual
        ventas_mes        = ventas_mes,
        gastos_mes        = gastos_mes,
        # Alertas de insumos
        insumos_criticos  = insumos_criticos,
        # Rol del usuario
        mi_rol            = mi_rol,
    )


# ═══════════════════════════════════════════════════════════════
# INVENTARIO (lista de lotes activos)
# ═══════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════
# CREAR LOTE (solo admin)
# ═══════════════════════════════════════════════════════════════
@bp.route("/crear_lote", methods=["POST"])
@solo_admin
def crear_lote():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    nombre   = request.form.get("nombre",   "").strip()
    tipo     = request.form.get("tipo",     "").strip()
    raza     = request.form.get("raza",     "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo",    "").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([nombre, tipo, raza, cantidad, costo, fecha]):
        flash("Completa todos los campos del lote.", "error")
        return redirect("/inventario")

    try:
        cantidad = int(cantidad)
        costo    = round(float(costo), 2)
        if cantidad <= 0 or costo < 0:
            raise ValueError
    except ValueError:
        flash("Cantidad o costo inválido.", "error")
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
    flash(f"✅ Lote '{nombre}' creado con {cantidad} animales.", "success")
    return redirect("/inventario")


# ═══════════════════════════════════════════════════════════════
# EDITAR LOTE (solo admin)
# ═══════════════════════════════════════════════════════════════
@bp.route("/editar_lote/<lote_id>", methods=["GET", "POST"])
@solo_admin
def editar_lote(lote_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/inventario")

    if request.method == "GET":
        return render_template("editar_lote.html", lote=lote[0], mi_rol=mi_rol)

    nombre   = request.form.get("nombre",   "").strip()
    tipo     = request.form.get("tipo",     "").strip()
    raza     = request.form.get("raza",     "").strip()
    cantidad = request.form.get("cantidad", "").strip()
    costo    = request.form.get("costo",    "").strip()
    fecha    = request.form.get("fecha",    "").strip()

    if not all([nombre, tipo, raza, cantidad, costo, fecha]):
        flash("Completa todos los campos.", "error")
        return redirect(f"/editar_lote/{lote_id}")

    try:
        cantidad = int(cantidad)
        costo    = round(float(costo), 2)
    except ValueError:
        flash("Valores inválidos.", "error")
        return redirect(f"/editar_lote/{lote_id}")

    backup_automatico(owner_id)
    sb_patch("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}", {
        "nombre":          nombre,
        "tipo":            tipo,
        "raza":            raza,
        "cantidad_actual": cantidad,
        "costo_compra":    costo,
        "fecha":           fecha,
    })
    flash(f"✅ Lote '{nombre}' actualizado.", "success")
    return redirect("/inventario")


# ═══════════════════════════════════════════════════════════════
# ARCHIVAR LOTE (solo admin)
# ═══════════════════════════════════════════════════════════════
@bp.route("/archivar_lote/<lote_id>", methods=["POST"])
@solo_admin
def archivar_lote(lote_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/inventario")

    backup_automatico(owner_id)
    sb_patch("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}", {"activo": False})
    flash(f"📦 Lote '{lote[0]['nombre']}' archivado.", "success")
    return redirect("/inventario")


# ═══════════════════════════════════════════════════════════════
# ELIMINAR LOTE (solo admin)
# ═══════════════════════════════════════════════════════════════
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
    for tabla in ("ventas", "gastos", "sanitario", "produccion", "bajas", "pesajes"):
        sb_delete(tabla, f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    sb_delete("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    flash(f"🗑 Lote '{lote[0]['nombre']}' eliminado.", "success")
    return redirect("/inventario")


# ═══════════════════════════════════════════════════════════════
# HISTORIAL DE LOTES INACTIVOS (solo admin)
# ═══════════════════════════════════════════════════════════════
@bp.route("/lotes_historial")
@solo_admin
def lotes_historial():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.false")
    return render_template("lotes_historial.html", lotes=lotes, mi_rol=mi_rol)