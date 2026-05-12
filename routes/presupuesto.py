# routes/presupuesto.py
"""
Presupuesto y Proyecciones — ERP Pecuario

Permite al ganadero planificar ingresos y gastos estimados por lote y mes,
y comparar contra los valores reales registrados en ventas y gastos.
"""
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin
import datetime

bp = Blueprint("presupuesto", __name__)

MESES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]


def _fmt(v):
    return round(float(v or 0), 2)


def _reales_del_mes(owner_id: int, lote_id: int | None,
                    anio: int, mes: int) -> dict:
    """Calcula ingresos y gastos reales del mes desde ventas y gastos."""
    mes_str = f"{anio}-{mes:02d}"

    q_base = f"usuario_id=eq.{owner_id}"
    if lote_id:
        q_base += f"&lote_id=eq.{lote_id}"

    ventas = sb_get("ventas", q_base + f"&fecha=gte.{mes_str}-01&fecha=lte.{mes_str}-31")
    gastos = sb_get("gastos", q_base + f"&fecha=gte.{mes_str}-01&fecha=lte.{mes_str}-31")

    return {
        "ingresos": _fmt(sum(_fmt(v.get("total", 0)) for v in ventas)),
        "gastos":   _fmt(sum(_fmt(g.get("costo", 0)) for g in gastos)),
    }


# ── Vista principal ────────────────────────────────────────────────────────────
@bp.route("/presupuesto")
def presupuesto():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    if not es_premium_owner(session["user_id"]):
        return render_template("premium_requerido.html", funcion="Calendario de Actividades")

    hoy      = datetime.date.today()
    anio     = int(request.args.get("anio",    hoy.year))
    mes      = int(request.args.get("mes",     hoy.month))
    lote_id  = request.args.get("lote_id", "")

    mes  = max(1, min(12, mes))
    anio = max(hoy.year - 2, min(hoy.year + 2, anio))

    lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.true")

    # Partidas del mes
    q = (f"usuario_id=eq.{owner_id}"
         f"&mes=eq.{mes}&anio=eq.{anio}&order=tipo.asc,concepto.asc")
    if lote_id:
        q += f"&lote_id=eq.{lote_id}"

    partidas  = sb_get("presupuesto", q)
    lotes_idx = {l["id"]: l["nombre"] for l in sb_get("lotes", f"usuario_id=eq.{owner_id}")}

    for p in partidas:
        p["lote_nombre"]    = lotes_idx.get(p.get("lote_id"), "Sin lote")
        p["monto_estimado"] = _fmt(p.get("monto_estimado", 0))
        p["monto_real"]     = _fmt(p.get("monto_real")) if p.get("monto_real") is not None else None

    # Totales estimados
    ing_est = _fmt(sum(p["monto_estimado"] for p in partidas if p["tipo"] == "ingreso"))
    gas_est = _fmt(sum(p["monto_estimado"] for p in partidas if p["tipo"] == "gasto"))
    res_est = _fmt(ing_est - gas_est)

    # Valores reales del mes
    lid = int(lote_id) if lote_id else None
    reales    = _reales_del_mes(owner_id, lid, anio, mes)
    res_real  = _fmt(reales["ingresos"] - reales["gastos"])

    # Navegación de meses
    if mes == 1:
        mes_ant, anio_ant = 12, anio - 1
    else:
        mes_ant, anio_ant = mes - 1, anio
    if mes == 12:
        mes_sig, anio_sig = 1, anio + 1
    else:
        mes_sig, anio_sig = mes + 1, anio

    return render_template(
        "presupuesto.html",
        partidas   = partidas,
        lotes      = lotes,
        lote_id    = lote_id,
        anio       = anio,
        mes        = mes,
        mes_nombre = MESES_ES[mes - 1],
        ing_est    = ing_est,
        gas_est    = gas_est,
        res_est    = res_est,
        reales     = reales,
        res_real   = res_real,
        mes_ant    = mes_ant, anio_ant = anio_ant,
        mes_sig    = mes_sig, anio_sig = anio_sig,
        mi_rol     = mi_rol,
    )


# ── Agregar partida ────────────────────────────────────────────────────────────
@bp.route("/agregar_partida", methods=["POST"])
def agregar_partida():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lote_id  = request.form.get("lote_id",        "").strip() or None
    concepto = request.form.get("concepto",        "").strip()
    tipo     = request.form.get("tipo",            "gasto").strip()
    monto    = request.form.get("monto_estimado",  "").strip()
    mes      = request.form.get("mes",             "").strip()
    anio     = request.form.get("anio",            "").strip()
    notas    = request.form.get("notas",           "").strip() or None

    if not all([concepto, tipo, monto, mes, anio]):
        flash("Completa todos los campos obligatorios.", "error")
        return redirect(f"/presupuesto?mes={mes}&anio={anio}&lote_id={lote_id or ''}")

    try:
        if lote_id: lote_id = int(lote_id)
        monto = round(float(monto), 2)
        mes   = int(mes)
        anio  = int(anio)
        if monto <= 0 or tipo not in ("ingreso", "gasto"):
            raise ValueError
    except ValueError:
        flash("Valores inválidos.", "error")
        return redirect("/presupuesto")

    if lote_id and not sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}"):
        flash("Lote no encontrado.", "error")
        return redirect("/presupuesto")

    backup_automatico(owner_id)
    sb_post("presupuesto", {
        "usuario_id":     owner_id,
        "lote_id":        lote_id,
        "concepto":       concepto,
        "tipo":           tipo,
        "monto_estimado": monto,
        "mes":            mes,
        "anio":           anio,
        "notas":          notas,
    })
    flash(f"✅ Partida '{concepto}' agregada.", "success")
    return redirect(f"/presupuesto?mes={mes}&anio={anio}&lote_id={lote_id or ''}")


# ── Marcar como cumplido y actualizar monto real ───────────────────────────────
@bp.route("/cumplir_partida/<int:partida_id>", methods=["POST"])
def cumplir_partida(partida_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    partida = sb_get("presupuesto", f"id=eq.{partida_id}&usuario_id=eq.{owner_id}")
    if not partida:
        return jsonify({"ok": False}), 404

    monto_real = request.form.get("monto_real", "").strip()
    try:
        monto_real = round(float(monto_real), 2) if monto_real else None
    except ValueError:
        monto_real = None

    sb_patch("presupuesto", f"id=eq.{partida_id}&usuario_id=eq.{owner_id}", {
        "cumplido":   True,
        "monto_real": monto_real,
    })
    flash("✅ Partida marcada como cumplida.", "success")
    p = partida[0]
    return redirect(f"/presupuesto?mes={p['mes']}&anio={p['anio']}")


# ── Eliminar partida (solo admin) ──────────────────────────────────────────────
@bp.route("/eliminar_partida/<int:partida_id>", methods=["POST"])
@solo_admin
def eliminar_partida(partida_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    partida = sb_get("presupuesto", f"id=eq.{partida_id}&usuario_id=eq.{owner_id}")
    if not partida:
        flash("Partida no encontrada.", "error")
        return redirect("/presupuesto")

    p = partida[0]
    sb_delete("presupuesto", f"id=eq.{partida_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Partida eliminada.", "success")
    return redirect(f"/presupuesto?mes={p['mes']}&anio={p['anio']}")