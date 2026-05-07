# routes/reportes.py
from flask import Blueprint, render_template, redirect, session, request, Response
from config import sb_get
from routes.permisos import get_granja_info, solo_admin
import csv
import io

bp = Blueprint("reportes", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ================= HISTORIAL con filtros (solo admin) =================
@bp.route("/historial")
@solo_admin
def historial():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lotes   = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    ventas  = sb_get("ventas", f"usuario_id=eq.{owner_id}")
    gastos  = sb_get("gastos", f"usuario_id=eq.{owner_id}")

    lotes_idx = {l["id"]: l["nombre"] for l in lotes}
    registro  = []

    for l in lotes:
        registro.append({
            "tipo":    "Compra",
            "lote":    l.get("nombre", ""),
            "detalle": f"{l.get('cantidad_inicial','')} animales — {l.get('tipo','')} {l.get('raza','')}",
            "valor":   _fmt(l.get("costo_compra", 0)),
            "fecha":   l.get("fecha", ""),
        })
    for v in ventas:
        registro.append({
            "tipo":    "Venta",
            "lote":    lotes_idx.get(v.get("lote_id"), "Desconocido"),
            "detalle": f"{v.get('cantidad','')} animales vendidos",
            "valor":   _fmt(v.get("total", 0)),
            "fecha":   v.get("fecha", ""),
        })
    for g in gastos:
        registro.append({
            "tipo":    "Gasto",
            "lote":    lotes_idx.get(g.get("lote_id"), "Desconocido"),
            "detalle": f"{g.get('nombre','')} — {g.get('cantidad','')}",
            "valor":   _fmt(g.get("costo", 0)),
            "fecha":   g.get("fecha", ""),
        })

    registro.sort(key=lambda x: x["fecha"] or "", reverse=True)

    filtro_tipo  = request.args.get("tipo",  "")
    filtro_desde = request.args.get("desde", "")
    filtro_hasta = request.args.get("hasta", "")
    filtro_lote  = request.args.get("lote",  "")

    if filtro_tipo:
        registro = [r for r in registro if r["tipo"] == filtro_tipo]
    if filtro_desde:
        registro = [r for r in registro if r["fecha"] >= filtro_desde]
    if filtro_hasta:
        registro = [r for r in registro if r["fecha"] <= filtro_hasta]
    if filtro_lote:
        registro = [r for r in registro if filtro_lote.lower() in r["lote"].lower()]

    nombres_lotes = sorted({l.get("nombre","") for l in lotes if l.get("nombre")})

    return render_template(
        "historial.html",
        historial=registro,
        filtro_tipo=filtro_tipo,
        filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta,
        filtro_lote=filtro_lote,
        nombres_lotes=nombres_lotes,
    )


# ================= REPORTES (solo admin) =================
@bp.route("/reportes")
@solo_admin
def reportes():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lotes      = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    all_gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}")
    all_ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}")

    gastos_por_lote = {}
    for g in all_gastos:
        lid = g.get("lote_id")
        gastos_por_lote[lid] = _fmt(gastos_por_lote.get(lid, 0) + _fmt(g.get("costo", 0)))

    ventas_por_lote = {}
    for v in all_ventas:
        lid = v.get("lote_id")
        ventas_por_lote[lid] = _fmt(ventas_por_lote.get(lid, 0) + _fmt(v.get("total", 0)))

    resultado = []
    for l in lotes:
        lote_id      = l.get("id")
        inversion    = _fmt(l.get("costo_compra", 0))
        total_gastos = gastos_por_lote.get(lote_id, 0)
        total_ventas = ventas_por_lote.get(lote_id, 0)
        ganancia     = _fmt(total_ventas - _fmt(inversion + total_gastos))

        resultado.append({
            "id":        lote_id,
            "nombre":    l.get("nombre", "Sin nombre"),
            "tipo":      l.get("tipo", ""),
            "raza":      l.get("raza", ""),
            "activo":    l.get("activo", False),
            "inversion": inversion,
            "gastos":    total_gastos,
            "ventas":    total_ventas,
            "ganancia":  ganancia,
        })

    return render_template("reportes.html", lotes=resultado)


# ================= DETALLE DE LOTE (solo admin) =================
@bp.route("/detalle_lote/<lote_id>")
@solo_admin
def detalle_lote(lote_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        return redirect("/inventario")

    ventas = sb_get("ventas", f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.desc")
    gastos = sb_get("gastos", f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.desc")

    l            = lote[0]
    inversion    = _fmt(l.get("costo_compra", 0))
    total_gastos = _fmt(sum(_fmt(g.get("costo", 0)) for g in gastos))
    total_ventas = _fmt(sum(_fmt(v.get("total", 0)) for v in ventas))
    ganancia     = _fmt(total_ventas - _fmt(inversion + total_gastos))

    return render_template(
        "detalle_lote.html",
        lote=l,
        ventas=ventas,
        gastos=gastos,
        inversion=inversion,
        total_gastos=total_gastos,
        total_ventas=total_ventas,
        ganancia=ganancia,
    )


# ================= EXPORTAR CSV (solo admin) =================
@bp.route("/exportar_csv")
@solo_admin
def exportar_csv():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    lotes      = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    all_gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}")
    all_ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}")

    lotes_idx = {l["id"]: l["nombre"] for l in lotes}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Tipo", "Lote", "Detalle", "Valor ($)", "Fecha"])

    for l in lotes:
        writer.writerow([
            "Compra", l.get("nombre",""),
            f"{l.get('cantidad_inicial','')} animales — {l.get('tipo','')} {l.get('raza','')}",
            _fmt(l.get("costo_compra", 0)),
            l.get("fecha",""),
        ])
    for v in all_ventas:
        writer.writerow([
            "Venta",
            lotes_idx.get(v.get("lote_id"), "Desconocido"),
            f"{v.get('cantidad','')} animales vendidos",
            _fmt(v.get("total", 0)),
            v.get("fecha",""),
        ])
    for g in all_gastos:
        writer.writerow([
            "Gasto",
            lotes_idx.get(g.get("lote_id"), "Desconocido"),
            f"{g.get('nombre','')} — {g.get('cantidad','')}",
            _fmt(g.get("costo", 0)),
            g.get("fecha",""),
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=historial_pecuario.csv"}
    )