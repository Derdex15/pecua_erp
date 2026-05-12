# routes/sanitario.py
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin, es_premium_owner
import datetime

bp = Blueprint("sanitario", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


def generar_alertas(owner_id):
    """
    Revisa registros sanitarios y crea alertas para los próximos 7 días.

    Fix de deduplicación: filtra por [sid:N] en el mensaje, donde N es el
    id único del registro sanitario. Esto garantiza exactamente 1 alerta por
    evento por día, incluso cuando vencen múltiples vacunas del mismo lote
    el mismo día (bug original: filtraba solo por lote_id + fecha + tipo).
    """
    hoy       = datetime.date.today()
    en_7_dias = hoy + datetime.timedelta(days=7)

    proximos = sb_get(
        "sanitario",
        f"usuario_id=eq.{owner_id}"
        f"&proxima_dosis=gte.{hoy}"
        f"&proxima_dosis=lte.{en_7_dias}"
    )

    lotes     = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    lotes_idx = {l["id"]: l["nombre"] for l in lotes}

    for r in proximos:
        lote_nombre    = lotes_idx.get(r.get("lote_id"), "Desconocido")
        dias_restantes = (datetime.date.fromisoformat(r["proxima_dosis"]) - hoy).days

        if dias_restantes == 0:
            mensaje = f"⚠️ HOY vence: {r['nombre']} en lote {lote_nombre} [sid:{r['id']}]"
        elif dias_restantes == 1:
            mensaje = f"⚠️ MAÑANA vence: {r['nombre']} en lote {lote_nombre} [sid:{r['id']}]"
        else:
            mensaje = (f"📅 En {dias_restantes} días vence: "
                       f"{r['nombre']} en lote {lote_nombre} [sid:{r['id']}]")

        # Filtrar por el ID único del registro (garantiza 1 alerta por evento)
        existente = sb_get(
            "alertas",
            f"usuario_id=eq.{owner_id}"
            f"&tipo=eq.vacuna"
            f"&fecha_alerta=eq.{hoy}"
            f"&mensaje=ilike.*[sid:{r['id']}]*"
        )
        if not existente:
            sb_post("alertas", {
                "usuario_id":   owner_id,
                "lote_id":      r.get("lote_id"),
                "tipo":         "vacuna",
                "mensaje":      mensaje,
                "fecha_alerta": str(hoy),
                "leida":        False,
            })

    # ── Alertas de stock bajo (≤3 animales en lote activo) ────────────────────
    lotes_activos = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.true")
    for l in lotes_activos:
        if l.get("cantidad_actual", 0) <= 3:
            existente = sb_get(
                "alertas",
                f"usuario_id=eq.{owner_id}"
                f"&lote_id=eq.{l['id']}"
                f"&fecha_alerta=eq.{hoy}"
                f"&tipo=eq.stock_bajo"
            )
            if not existente:
                sb_post("alertas", {
                    "usuario_id":   owner_id,
                    "lote_id":      l["id"],
                    "tipo":         "stock_bajo",
                    "mensaje":      (f"⚠️ Stock bajo: solo {l['cantidad_actual']} "
                                     f"animales en '{l['nombre']}'"),
                    "fecha_alerta": str(hoy),
                    "leida":        False,
                })


# ── Vista principal ────────────────────────────────────────────────────────────
@bp.route("/sanitario")
def sanitario():
    if "user_id" not in session:
        return redirect("/login")

    user_id          = session["user_id"]
    owner_id, mi_rol = get_granja_info(user_id)

    if not es_premium_owner(user_id):
        return render_template("premium_requerido.html", funcion="Control Sanitario")

    lotes     = sb_get("lotes",     f"usuario_id=eq.{owner_id}&activo=eq.true")
    registros = sb_get("sanitario", f"usuario_id=eq.{owner_id}&order=fecha.desc")

    todos_lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    lotes_idx   = {l["id"]: l["nombre"] for l in todos_lotes}

    for r in registros:
        r["lote_nombre"] = lotes_idx.get(r.get("lote_id"), "Desconocido")
        r["costo"]       = _fmt(r.get("costo", 0))
        if r.get("proxima_dosis"):
            dias = (datetime.date.fromisoformat(r["proxima_dosis"]) - datetime.date.today()).days
            r["dias_proxima"] = dias
        else:
            r["dias_proxima"] = None

    generar_alertas(owner_id)

    return render_template("sanitario.html", lotes=lotes, registros=registros, mi_rol=mi_rol)


# ── Agregar registro (operador y admin) ───────────────────────────────────────
@bp.route("/agregar_sanitario", methods=["POST"])
def agregar_sanitario():
    if "user_id" not in session:
        return redirect("/login")

    user_id     = session["user_id"]
    owner_id, _ = get_granja_info(user_id)

    if not es_premium_owner(user_id):
        return redirect("/sanitario")

    lote_id       = request.form.get("lote_id",       "").strip()
    tipo          = request.form.get("tipo",           "").strip()
    nombre        = request.form.get("nombre",         "").strip()
    fecha         = request.form.get("fecha",          "").strip()
    proxima_dosis = request.form.get("proxima_dosis",  "").strip() or None
    costo         = request.form.get("costo",          "0").strip()
    notas         = request.form.get("notas",          "").strip()

    if not all([lote_id, tipo, nombre, fecha]):
        flash("Completa los campos obligatorios.", "error")
        return redirect("/sanitario")

    try:
        lote_id = int(lote_id)
        costo   = round(float(costo or 0), 2)
    except ValueError:
        flash("Lote o costo inválido.", "error")
        return redirect("/sanitario")

    if not sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}"):
        flash("Lote no encontrado.", "error")
        return redirect("/sanitario")

    backup_automatico(owner_id)
    sb_post("sanitario", {
        "usuario_id":    owner_id,
        "lote_id":       lote_id,
        "tipo":          tipo,
        "nombre":        nombre,
        "fecha":         fecha,
        "proxima_dosis": proxima_dosis,
        "costo":         costo,
        "notas":         notas or None,
    })
    flash(f"✅ Registro sanitario '{nombre}' guardado.", "success")
    return redirect("/sanitario")


# ── Editar registro (solo admin) ──────────────────────────────────────────────
@bp.route("/editar_sanitario/<registro_id>", methods=["GET", "POST"])
@solo_admin
def editar_sanitario(registro_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    registro = sb_get("sanitario", f"id=eq.{registro_id}&usuario_id=eq.{owner_id}")
    if not registro:
        flash("Registro no encontrado.", "error")
        return redirect("/sanitario")

    if request.method == "GET":
        lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}&activo=eq.true")
        return render_template("editar_sanitario.html",
                               registro=registro[0], lotes=lotes, mi_rol=mi_rol)

    lote_id       = request.form.get("lote_id",       "").strip()
    tipo          = request.form.get("tipo",           "").strip()
    nombre        = request.form.get("nombre",         "").strip()
    fecha         = request.form.get("fecha",          "").strip()
    proxima_dosis = request.form.get("proxima_dosis",  "").strip() or None
    costo         = request.form.get("costo",          "0").strip()
    notas         = request.form.get("notas",          "").strip()

    if not all([lote_id, tipo, nombre, fecha]):
        flash("Completa los campos obligatorios.", "error")
        return redirect(f"/editar_sanitario/{registro_id}")

    try:
        lote_id = int(lote_id)
        costo   = round(float(costo or 0), 2)
    except ValueError:
        flash("Lote o costo inválido.", "error")
        return redirect(f"/editar_sanitario/{registro_id}")

    backup_automatico(owner_id)
    sb_patch("sanitario", f"id=eq.{registro_id}&usuario_id=eq.{owner_id}", {
        "lote_id":       lote_id,
        "tipo":          tipo,
        "nombre":        nombre,
        "fecha":         fecha,
        "proxima_dosis": proxima_dosis,
        "costo":         costo,
        "notas":         notas or None,
    })
    flash("✅ Registro sanitario actualizado.", "success")
    return redirect("/sanitario")


# ── Eliminar registro (solo admin) ────────────────────────────────────────────
@bp.route("/eliminar_sanitario/<registro_id>", methods=["POST"])
@solo_admin
def eliminar_sanitario(registro_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    if not sb_get("sanitario", f"id=eq.{registro_id}&usuario_id=eq.{owner_id}"):
        flash("Registro no encontrado.", "error")
        return redirect("/sanitario")

    backup_automatico(owner_id)
    sb_delete("sanitario", f"id=eq.{registro_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Registro sanitario eliminado.", "success")
    return redirect("/sanitario")


# ── API: historial sanitario de un lote (para PDF) ────────────────────────────
@bp.route("/api/sanitario/<lote_id>")
def api_sanitario_lote(lote_id):
    if "user_id" not in session:
        return jsonify([])
    owner_id, _ = get_granja_info(session["user_id"])
    datos = sb_get("sanitario",
                   f"lote_id=eq.{lote_id}&usuario_id=eq.{owner_id}&order=fecha.desc")
    return jsonify(datos)