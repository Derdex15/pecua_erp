# routes/inventario.py
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin
import datetime

bp = Blueprint("inventario", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ================= DASHBOARD =================
@bp.route("/")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])

    lotes  = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}")
    gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}")
    bajas  = sb_get("bajas",  f"usuario_id=eq.{owner_id}")

    lotes_activos = [l for l in lotes if l.get("activo", True) and l.get("cantidad_actual", 0) > 0]

    # ── KPIs financieros ─────────────────────────────────────────
    total_animales = sum(l.get("cantidad_actual", 0) for l in lotes_activos)
    total_compra   = _fmt(sum(_fmt(l.get("costo_compra", 0)) for l in lotes))
    total_ventas   = _fmt(sum(_fmt(v.get("total", 0))        for v in ventas))
    total_gastos   = _fmt(sum(_fmt(g.get("costo", 0))        for g in gastos))
    inversion      = _fmt(total_compra + total_gastos)
    ganancia       = _fmt(total_ventas - inversion)

    # ── KPIs ganaderos — ítem 13 ─────────────────────────────────

    # 1. Mortalidad % (muertes / total animales que han pasado por la granja)
    total_inicial_historico = sum(l.get("cantidad_inicial", 0) for l in lotes)
    total_muertes = sum(b.get("cantidad", 0) for b in bajas if b.get("tipo") == "muerte")
    pct_mortalidad = round((total_muertes / total_inicial_historico * 100), 1) \
                     if total_inicial_historico > 0 else 0.0

    # 2. Total bajas del período (todas las causas)
    total_bajas = sum(b.get("cantidad", 0) for b in bajas)

    # 3. Precio promedio por animal vendido
    total_animales_vendidos = sum(v.get("cantidad", 0) for v in ventas)
    precio_prom_venta = _fmt(total_ventas / total_animales_vendidos) \
                        if total_animales_vendidos > 0 else 0.0

    # 4. ROI % (retorno sobre la inversión)
    roi = round((ganancia / inversion * 100), 1) if inversion > 0 else 0.0

    # 5. KPIs del mes actual
    hoy   = datetime.date.today()
    mes   = hoy.strftime("%Y-%m")
    ventas_mes = _fmt(sum(_fmt(v.get("total", 0)) for v in ventas
                          if (v.get("fecha") or "")[:7] == mes))
    gastos_mes = _fmt(sum(_fmt(g.get("costo", 0)) for g in gastos
                          if (g.get("fecha") or "")[:7] == mes))

    # 6. Desglose por tipo/raza para la barra visual
    detalle = {}
    for l in lotes_activos:
        tipo = l.get("tipo", "Desconocido")
        raza = l.get("raza", "Desconocido")
        detalle.setdefault(tipo, {})
        detalle[tipo][raza] = detalle[tipo].get(raza, 0) + l.get("cantidad_actual", 0)

    # 7. Alertas de stock bajo en insumos (para badge en dashboard)
    insumos_criticos = 0
    try:
        insumos = sb_get("insumos", f"usuario_id=eq.{owner_id}")
        insumos_criticos = sum(1 for i in insumos
                               if _fmt(i.get("cantidad", 0)) <= _fmt(i.get("stock_min", 0))
                               and _fmt(i.get("stock_min", 0)) > 0)
    except Exception:
        pass

    return render_template(
        "dashboard.html",
        # Financieros
        total_animales=total_animales,
        total_ventas=total_ventas,
        inversion=inversion,
        ganancia=ganancia,
        # Ganaderos
        pct_mortalidad=pct_mortalidad,
        total_muertes=total_muertes,
        total_bajas=total_bajas,
        precio_prom_venta=precio_prom_venta,
        roi=roi,
        ventas_mes=ventas_mes,
        gastos_mes=gastos_mes,
        # Desglose
        detalle=detalle,
        insumos_criticos=insumos_criticos,
        mi_rol=mi_rol,
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


# ================= CREAR LOTE =================
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
        flash("Cantidad debe ser entero positivo y costo un número válido.", "error")
        return redirect("/inventario")
    backup_automatico(owner_id)
    sb_post("lotes", {
        "usuario_id": owner_id, "nombre": nombre, "tipo": tipo, "raza": raza,
        "cantidad_inicial": cantidad, "cantidad_actual": cantidad,
        "costo_compra": costo, "fecha": fecha, "activo": True,
    })
    flash(f"✅ Lote '{nombre}' creado.", "success")
    return redirect("/inventario")


# ================= EDITAR LOTE =================
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
    costo  = request.form.get("costo",  "").strip()
    fecha  = request.form.get("fecha",  "").strip()
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
    sb_patch("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}",
             {"nombre": nombre, "costo_compra": costo, "fecha": fecha})
    flash(f"✅ Lote '{nombre}' actualizado.", "success")
    return redirect("/inventario")


# ================= ELIMINAR LOTE =================
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
    flash("🗑 Lote eliminado.", "success")
    return redirect("/inventario")


# ================= LOTES HISTORIAL =================
@bp.route("/lotes_historial")
def lotes_historial():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.false")
    return render_template("lotes_historial.html", lotes=lotes)