# routes/calendario.py
"""
Calendario Visual — ERP Pecuario

Muestra en vista mensual:
  💉 Vacunas/sanitario próximas (proxima_dosis)
  🐣 Partos estimados (reproduccion.fecha_esperada)
  ⚠️  Alertas activas no leídas

No requiere tablas nuevas. Usa sanitario, reproduccion y alertas.
"""
from flask import Blueprint, render_template, redirect, session, request, jsonify
from config import sb_get
from routes.permisos import get_granja_info, es_premium_owner  # ← fix: agregar es_premium_owner
import datetime

bp = Blueprint("calendario", __name__)

MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]

DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _dia(fecha_str: str) -> int:
    """Extrae el día (int) de un string 'YYYY-MM-DD'."""
    try:
        return int(fecha_str.split("-")[2])
    except Exception:
        return 0


def _eventos_del_mes(owner_id: int, anio: int, mes: int) -> dict:
    """
    Recopila eventos de todas las fuentes para el mes dado.
    Retorna dict {dia: [{"tipo", "color", "icon", "texto"}, ...]}
    """
    desde = datetime.date(anio, mes, 1)
    if mes == 12:
        hasta = datetime.date(anio + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        hasta = datetime.date(anio, mes + 1, 1) - datetime.timedelta(days=1)

    eventos: dict = {}

    # ── Índices de lotes y animales ───────────────────────────────────────────
    lotes_idx = {l["id"]: l["nombre"]
                 for l in sb_get("lotes", f"usuario_id=eq.{owner_id}")}
    animales_idx = {
        a["id"]: (a.get("nombre") or a.get("arete") or f"#{a['id']}")
        for a in sb_get("animales", f"usuario_id=eq.{owner_id}")
    }

    # ── Vacunas / sanitario ───────────────────────────────────────────────────
    san = sb_get(
        "sanitario",
        f"usuario_id=eq.{owner_id}"
        f"&proxima_dosis=gte.{desde}"
        f"&proxima_dosis=lte.{hasta}"
    )
    for r in san:
        d = _dia(r.get("proxima_dosis", ""))
        if not d:
            continue
        lote = lotes_idx.get(r.get("lote_id"), "Lote ?")
        eventos.setdefault(d, []).append({
            "tipo":   "vacuna",
            "color":  "#3498db",
            "icon":   "💉",
            "texto":  f"{r['nombre']} — {lote}",
        })

    # ── Partos estimados ──────────────────────────────────────────────────────
    repro = sb_get(
        "reproduccion",
        f"usuario_id=eq.{owner_id}"
        f"&fecha_esperada=gte.{desde}"
        f"&fecha_esperada=lte.{hasta}"
    )
    for r in repro:
        d = _dia(r.get("fecha_esperada", ""))
        if not d:
            continue
        animal = animales_idx.get(r.get("animal_id"), "Animal ?")
        eventos.setdefault(d, []).append({
            "tipo":  "parto",
            "color": "#e67e22",
            "icon":  "🐣",
            "texto": f"Parto estimado — {animal}",
        })

    # ── Alertas no leídas ─────────────────────────────────────────────────────
    alertas = sb_get(
        "alertas",
        f"usuario_id=eq.{owner_id}"
        f"&fecha_alerta=gte.{desde}"
        f"&fecha_alerta=lte.{hasta}"
        f"&leida=eq.false"
    )
    for a in alertas:
        d = _dia(a.get("fecha_alerta", ""))
        if not d:
            continue
        eventos.setdefault(d, []).append({
            "tipo":  "alerta",
            "color": "#e74c3c",
            "icon":  "⚠️",
            "texto": (a.get("mensaje") or "Alerta")[:70],
        })

    return eventos


@bp.route("/calendario")
def calendario():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    if not es_premium_owner(session["user_id"]):
        return render_template("premium_requerido.html", funcion="Calendario de Actividades")

    hoy  = datetime.date.today()
    anio = int(request.args.get("anio", hoy.year))
    mes  = int(request.args.get("mes",  hoy.month))

    # Limitar navegación
    mes  = max(1, min(12, mes))
    anio = max(hoy.year - 1, min(hoy.year + 2, anio))

    desde    = datetime.date(anio, mes, 1)
    if mes == 12:
        hasta = datetime.date(anio + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        hasta = datetime.date(anio, mes + 1, 1) - datetime.timedelta(days=1)

    dias_en_mes = (hasta - desde).days + 1
    primer_dia  = desde.weekday()   # 0 = lunes

    eventos = _eventos_del_mes(owner_id, anio, mes)

    if mes == 1:
        mes_ant, anio_ant = 12, anio - 1
    else:
        mes_ant, anio_ant = mes - 1, anio

    if mes == 12:
        mes_sig, anio_sig = 1, anio + 1
    else:
        mes_sig, anio_sig = mes + 1, anio

    return render_template(
        "calendario.html",
        eventos      = eventos,
        anio         = anio,
        mes          = mes,
        mes_nombre   = MESES_ES[mes - 1],
        dias_es      = DIAS_ES,
        primer_dia   = primer_dia,
        dias_en_mes  = dias_en_mes,
        hoy          = hoy,
        mes_ant      = mes_ant,
        anio_ant     = anio_ant,
        mes_sig      = mes_sig,
        anio_sig     = anio_sig,
        mi_rol       = mi_rol,
    )


@bp.route("/api/calendario/eventos")
def api_eventos():
    """Retorna eventos del mes en JSON."""
    if "user_id" not in session:
        return jsonify([])
    owner_id, _ = get_granja_info(session["user_id"])
    hoy  = datetime.date.today()
    anio = int(request.args.get("anio", hoy.year))
    mes  = int(request.args.get("mes",  hoy.month))
    eventos = _eventos_del_mes(owner_id, anio, mes)
    resultado = []
    for dia, lista in eventos.items():
        for e in lista:
            resultado.append({"dia": dia, **e})
    return jsonify(sorted(resultado, key=lambda x: x["dia"]))