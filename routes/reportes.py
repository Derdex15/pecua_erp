# routes/reportes.py
from flask import Blueprint, render_template, redirect, session, request, Response
from config import sb_get
from routes.permisos import get_granja_info, solo_admin
import csv
import io
import datetime

bp = Blueprint("reportes", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ── Helpers compartidos ────────────────────────────────────────

def _construir_historial(owner_id):
    lotes      = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    ventas     = sb_get("ventas", f"usuario_id=eq.{owner_id}")
    gastos     = sb_get("gastos", f"usuario_id=eq.{owner_id}")
    lotes_idx  = {l["id"]: l["nombre"] for l in lotes}
    registro   = []
    for l in lotes:
        registro.append({"tipo": "Compra", "lote": l.get("nombre",""),
            "detalle": f"{l.get('cantidad_inicial','')} animales — {l.get('tipo','')} {l.get('raza','')}",
            "valor": _fmt(l.get("costo_compra",0)), "fecha": l.get("fecha","")})
    for v in ventas:
        registro.append({"tipo": "Venta", "lote": lotes_idx.get(v.get("lote_id"),"Desconocido"),
            "detalle": f"{v.get('cantidad','')} animales vendidos",
            "valor": _fmt(v.get("total",0)), "fecha": v.get("fecha","")})
    for g in gastos:
        registro.append({"tipo": "Gasto", "lote": lotes_idx.get(g.get("lote_id"),"Desconocido"),
            "detalle": f"{g.get('nombre','')} — {g.get('cantidad','')}",
            "valor": _fmt(g.get("costo",0)), "fecha": g.get("fecha","")})
    registro.sort(key=lambda x: x["fecha"] or "", reverse=True)
    return registro, lotes


# ── HISTORIAL ─────────────────────────────────────────────────
@bp.route("/historial")
@solo_admin
def historial():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    registro, lotes = _construir_historial(owner_id)

    filtro_tipo  = request.args.get("tipo",  "")
    filtro_desde = request.args.get("desde", "")
    filtro_hasta = request.args.get("hasta", "")
    filtro_lote  = request.args.get("lote",  "")
    if filtro_tipo:  registro = [r for r in registro if r["tipo"]  == filtro_tipo]
    if filtro_desde: registro = [r for r in registro if r["fecha"] >= filtro_desde]
    if filtro_hasta: registro = [r for r in registro if r["fecha"] <= filtro_hasta]
    if filtro_lote:  registro = [r for r in registro if filtro_lote.lower() in r["lote"].lower()]

    nombres_lotes = sorted({l.get("nombre","") for l in lotes if l.get("nombre")})
    return render_template("historial.html", historial=registro,
        filtro_tipo=filtro_tipo, filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta, filtro_lote=filtro_lote,
        nombres_lotes=nombres_lotes)


# ── REPORTES ──────────────────────────────────────────────────
@bp.route("/reportes")
@solo_admin
def reportes():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    lotes      = sb_get("lotes",  f"usuario_id=eq.{owner_id}")
    all_gastos = sb_get("gastos", f"usuario_id=eq.{owner_id}")
    all_ventas = sb_get("ventas", f"usuario_id=eq.{owner_id}")
    all_bajas  = sb_get("bajas",  f"usuario_id=eq.{owner_id}")

    gastos_por_lote = {}
    for g in all_gastos:
        lid = g.get("lote_id")
        gastos_por_lote[lid] = _fmt(gastos_por_lote.get(lid,0) + _fmt(g.get("costo",0)))
    ventas_por_lote = {}
    for v in all_ventas:
        lid = v.get("lote_id")
        ventas_por_lote[lid] = _fmt(ventas_por_lote.get(lid,0) + _fmt(v.get("total",0)))

    resultado = []
    for l in lotes:
        lid          = l.get("id")
        inversion    = _fmt(l.get("costo_compra",0))
        total_gastos = gastos_por_lote.get(lid,0)
        total_ventas = ventas_por_lote.get(lid,0)
        base         = _fmt(inversion + total_gastos)
        ganancia     = _fmt(total_ventas - base)
        roi_lote     = round((ganancia / base * 100), 1) if base > 0 else 0
        resultado.append({"id": lid, "nombre": l.get("nombre","Sin nombre"),
            "tipo": l.get("tipo",""), "raza": l.get("raza",""),
            "activo": l.get("activo",False), "inversion": inversion,
            "gastos": total_gastos, "ventas": total_ventas,
            "ganancia": ganancia, "roi": roi_lote})

    # ── KPIs globales (mismas fórmulas que el dashboard) ───────────
    total_compra = _fmt(sum(_fmt(l.get("costo_compra",0)) for l in lotes))
    total_gastos = _fmt(sum(_fmt(g.get("costo",0)) for g in all_gastos))
    total_ventas = _fmt(sum(_fmt(v.get("total",0)) for v in all_ventas))
    inversion    = _fmt(total_compra + total_gastos)
    ganancia     = _fmt(total_ventas - inversion)
    roi          = round((ganancia / inversion * 100), 1) if inversion > 0 else 0

    total_inicial  = sum(l.get("cantidad_inicial",0) for l in lotes)
    total_muertes  = sum(b.get("cantidad",0) for b in all_bajas if b.get("tipo") == "muerte")
    pct_mortalidad = round((total_muertes / total_inicial * 100), 1) if total_inicial > 0 else 0

    total_cab_vendidas = sum(_fmt(v.get("cantidad",0)) for v in all_ventas)
    precio_prom_venta  = _fmt(total_ventas / total_cab_vendidas) if total_cab_vendidas > 0 else 0

    # Costo por kg ganado (a partir de pesajes con lote asociado)
    costo_por_kg = None
    try:
        pesajes_lote = sb_get("pesajes",
                              f"usuario_id=eq.{owner_id}&lote_id=not.is.null&order=fecha.asc")
        if pesajes_lote and total_gastos > 0:
            lote_pesajes = {}
            for p in pesajes_lote:
                lid = p.get("lote_id")
                if lid:
                    lote_pesajes.setdefault(lid, []).append(_fmt(p.get("peso_kg",0)))
            kg_ganados = sum(
                max(pesos) - min(pesos)
                for pesos in lote_pesajes.values()
                if len(pesos) >= 2 and (max(pesos) - min(pesos)) > 0
            )
            if kg_ganados > 0:
                costo_por_kg = round(total_gastos / kg_ganados, 2)
    except Exception:
        pass

    return render_template(
        "reportes.html",
        lotes             = resultado,
        roi               = roi,
        ganancia          = ganancia,
        inversion         = inversion,
        total_ventas      = total_ventas,
        pct_mortalidad    = pct_mortalidad,
        total_muertes     = total_muertes,
        precio_prom_venta = precio_prom_venta,
        costo_por_kg      = costo_por_kg,
    )


# ── DETALLE DE LOTE ───────────────────────────────────────────
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
    inversion    = _fmt(l.get("costo_compra",0))
    total_gastos = _fmt(sum(_fmt(g.get("costo",0)) for g in gastos))
    total_ventas = _fmt(sum(_fmt(v.get("total",0)) for v in ventas))
    ganancia     = _fmt(total_ventas - _fmt(inversion + total_gastos))
    return render_template("detalle_lote.html", lote=l, ventas=ventas, gastos=gastos,
        inversion=inversion, total_gastos=total_gastos,
        total_ventas=total_ventas, ganancia=ganancia)


# ── EXPORTAR CSV ──────────────────────────────────────────────
@bp.route("/exportar_csv")
@solo_admin
def exportar_csv():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    registro, _ = _construir_historial(owner_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Tipo","Lote","Detalle","Valor ($)","Fecha"])
    for r in registro:
        writer.writerow([r["tipo"], r["lote"], r["detalle"], r["valor"], r["fecha"]])
    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=historial_pecuario.csv"})


# ── PDF FINANCIERO (por lote) — ítem 11 ──────────────────────
@bp.route("/exportar_pdf/lote/<lote_id>")
@solo_admin
def pdf_lote(lote_id):
    """Genera un PDF profesional con el resumen financiero y sanitario de un lote."""
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        return redirect("/reportes")

    l      = lote[0]
    ventas = sb_get("ventas",    f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.asc")
    gastos = sb_get("gastos",    f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.asc")
    sanit  = sb_get("sanitario", f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.asc")
    bajas  = sb_get("bajas",     f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.asc")

    inversion    = _fmt(l.get("costo_compra",0))
    total_gastos = _fmt(sum(_fmt(g.get("costo",0)) for g in gastos))
    total_ventas = _fmt(sum(_fmt(v.get("total",0)) for v in ventas))
    ganancia     = _fmt(total_ventas - (inversion + total_gastos))

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    VERDE  = colors.HexColor("#27ae60")
    GRIS   = colors.HexColor("#ecf0f1")
    ROJO   = colors.HexColor("#e74c3c")

    titulo_st  = ParagraphStyle("t", parent=styles["Title"],
                                 textColor=VERDE, spaceAfter=4)
    h2_st      = ParagraphStyle("h2", parent=styles["Heading2"],
                                 textColor=colors.HexColor("#2c3e50"), spaceBefore=10)
    normal_st  = styles["Normal"]
    derecha_st = ParagraphStyle("der", parent=normal_st, alignment=TA_RIGHT)

    story = []

    # Encabezado
    story.append(Paragraph("🐄 ERP Pecuario", titulo_st))
    story.append(Paragraph(f"Reporte del lote: <b>{l.get('nombre','')}</b>", h2_st))
    story.append(Paragraph(
        f"{l.get('tipo','').capitalize()} · {l.get('raza','')} · "
        f"Fecha inicio: {l.get('fecha','')} · "
        f"Generado: {datetime.date.today()}",
        normal_st))
    story.append(HRFlowable(width="100%", thickness=1, color=VERDE, spaceAfter=10))

    # Resumen financiero
    story.append(Paragraph("Resumen financiero", h2_st))
    resumen_data = [
        ["Concepto", "Monto"],
        ["Inversión inicial (compra)", f"${inversion:.2f}"],
        ["Gastos adicionales",         f"${total_gastos:.2f}"],
        ["Total ingresos (ventas)",    f"${total_ventas:.2f}"],
        ["Ganancia neta",              f"${ganancia:.2f}"],
    ]
    t_res = Table(resumen_data, colWidths=[11*cm, 5*cm])
    t_res.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  VERDE),
        ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("ALIGN",        (1,0), (1,-1),  "RIGHT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, GRIS]),
        ("FONTNAME",     (0,-1),(-1,-1), "Helvetica-Bold"),
        ("TEXTCOLOR",    (1,-1),(1,-1),
         VERDE if ganancia >= 0 else ROJO),
        ("GRID",         (0,0), (-1,-1), 0.5, colors.lightgrey),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
    ]))
    story.append(t_res)
    story.append(Spacer(1, 0.4*cm))

    # Inventario
    story.append(Paragraph("Inventario", h2_st))
    total_bajas = sum(b.get("cantidad",0) for b in bajas)
    inv_data = [
        ["Concepto", "Cantidad"],
        ["Animales iniciales",  str(l.get("cantidad_inicial",0))],
        ["Bajas (muerte/robo)", str(total_bajas)],
        ["Vendidos",            str(sum(v.get("cantidad",0) for v in ventas))],
        ["Actuales",            str(l.get("cantidad_actual",0))],
    ]
    t_inv = Table(inv_data, colWidths=[11*cm, 5*cm])
    t_inv.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), VERDE),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN",         (1,0), (1,-1), "RIGHT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, GRIS]),
        ("GRID",          (0,0),(-1,-1), 0.5, colors.lightgrey),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
    ]))
    story.append(t_inv)
    story.append(Spacer(1, 0.4*cm))

    # Gastos detallados
    if gastos:
        story.append(Paragraph("Detalle de gastos", h2_st))
        g_data = [["Fecha", "Insumo / Servicio", "Cant.", "Costo"]]
        for g in gastos:
            g_data.append([
                g.get("fecha",""),
                g.get("nombre",""),
                str(g.get("cantidad","")),
                f"${_fmt(g.get('costo',0)):.2f}",
            ])
        t_g = Table(g_data, colWidths=[3*cm, 8*cm, 2.5*cm, 2.5*cm])
        t_g.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), VERDE),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("ALIGN",         (3,0),(3,-1), "RIGHT"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRIS]),
            ("GRID",          (0,0),(-1,-1), 0.5, colors.lightgrey),
            ("FONTSIZE",      (0,0),(-1,-1), 9),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ]))
        story.append(t_g)
        story.append(Spacer(1, 0.4*cm))

    # Historial sanitario
    if sanit:
        story.append(Paragraph("Historial sanitario", h2_st))
        s_data = [["Fecha", "Tipo", "Producto", "Próx. dosis", "Costo"]]
        for s in sanit:
            s_data.append([
                s.get("fecha",""),
                s.get("tipo","").capitalize(),
                s.get("nombre",""),
                s.get("proxima_dosis","—") or "—",
                f"${_fmt(s.get('costo',0)):.2f}",
            ])
        t_s = Table(s_data, colWidths=[2.5*cm, 3*cm, 5*cm, 3*cm, 2.5*cm])
        t_s.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), VERDE),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRIS]),
            ("GRID",          (0,0),(-1,-1), 0.5, colors.lightgrey),
            ("FONTSIZE",      (0,0),(-1,-1), 9),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ]))
        story.append(t_s)

    # Pie de página
    story.append(Spacer(1, 0.6*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"Generado por ERP Pecuario · {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle("pie", parent=normal_st, textColor=colors.grey,
                       fontSize=8, alignment=TA_CENTER)))

    doc.build(story)
    buf.seek(0)
    nombre_archivo = f"reporte_{l.get('nombre','lote').replace(' ','_')}.pdf"
    return Response(buf.read(), mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"})


# ── PDF SANITARIO GLOBAL — ítem 11 ───────────────────────────
@bp.route("/exportar_pdf/sanitario")
@solo_admin
def pdf_sanitario():
    """PDF del historial sanitario completo — útil para el veterinario."""
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    todos_sanit = sb_get("sanitario", f"usuario_id=eq.{owner_id}&order=fecha.desc")
    lotes       = sb_get("lotes",     f"usuario_id=eq.{owner_id}")
    lotes_idx   = {l["id"]: l["nombre"] for l in lotes}

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    VERDE  = colors.HexColor("#27ae60")
    GRIS   = colors.HexColor("#ecf0f1")

    story = []
    story.append(Paragraph("🐄 ERP Pecuario — Historial Sanitario",
        ParagraphStyle("t", parent=styles["Title"], textColor=VERDE, spaceAfter=4)))
    story.append(Paragraph(
        f"Generado: {datetime.date.today()} · Total registros: {len(todos_sanit)}",
        styles["Normal"]))
    story.append(HRFlowable(width="100%", thickness=1, color=VERDE, spaceAfter=10))

    if todos_sanit:
        data = [["Fecha","Lote","Tipo","Producto","Próx. dosis","Costo"]]
        for s in todos_sanit:
            data.append([
                s.get("fecha",""),
                lotes_idx.get(s.get("lote_id"),"—"),
                s.get("tipo","").capitalize(),
                s.get("nombre",""),
                s.get("proxima_dosis","—") or "—",
                f"${_fmt(s.get('costo',0)):.2f}",
            ])
        t = Table(data, colWidths=[2.5*cm, 3.5*cm, 3*cm, 4*cm, 2.5*cm, 2*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), VERDE),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRIS]),
            ("GRID",          (0,0),(-1,-1), 0.5, colors.lightgrey),
            ("FONTSIZE",      (0,0),(-1,-1), 8),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("Sin registros sanitarios.", styles["Normal"]))

    story.append(Spacer(1, 0.6*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"ERP Pecuario · {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle("pie", parent=styles["Normal"], textColor=colors.grey,
                       fontSize=8, alignment=TA_CENTER)))

    doc.build(story)
    buf.seek(0)
    return Response(buf.read(), mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=historial_sanitario.pdf"})