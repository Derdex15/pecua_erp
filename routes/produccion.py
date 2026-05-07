# routes/produccion.py
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin, es_premium_owner
import datetime

bp = Blueprint("produccion", __name__)


def _fmt(valor):
    return round(float(valor or 0), 2)


# ================= VISTA PRODUCCIÓN =================
@bp.route("/produccion")
def produccion():
    if "user_id" not in session:
        return redirect("/login")

    user_id          = session["user_id"]
    owner_id, mi_rol = get_granja_info(user_id)

    if not es_premium_owner(user_id):
        return render_template("premium_requerido.html", funcion="Registro de Producción")

    lotes     = sb_get("lotes",      f"usuario_id=eq.{owner_id}&activo=eq.true")
    registros = sb_get("produccion", f"usuario_id=eq.{owner_id}&order=fecha.desc")

    todos_lotes = sb_get("lotes", f"usuario_id=eq.{owner_id}")
    lotes_idx   = {l["id"]: l["nombre"] for l in todos_lotes}

    for r in registros:
        r["lote_nombre"] = lotes_idx.get(r.get("lote_id"), "Desconocido")
        r["valor"]       = _fmt(r.get("valor", 0))

    lote_sel      = request.args.get("lote_id", "")
    grafico_datos = {}

    if lote_sel:
        datos_lote = sb_get("produccion",
                            f"usuario_id=eq.{owner_id}"
                            f"&lote_id=eq.{lote_sel}"
                            f"&order=fecha.asc")
        for d in datos_lote:
            t = d.get("tipo", "")
            grafico_datos.setdefault(t, [])
            grafico_datos[t].append({
                "fecha": d.get("fecha", ""),
                "valor": _fmt(d.get("valor", 0))
            })

    return render_template(
        "produccion.html",
        lotes=lotes,
        registros=registros,
        lote_sel=lote_sel,
        grafico_datos=grafico_datos,
        mi_rol=mi_rol,
    )


# ================= AGREGAR REGISTRO (operador y admin) =================
@bp.route("/agregar_produccion", methods=["POST"])
def agregar_produccion():
    if "user_id" not in session:
        return redirect("/login")

    user_id     = session["user_id"]
    owner_id, _ = get_granja_info(user_id)

    if not es_premium_owner(user_id):
        return redirect("/produccion")

    lote_id = request.form.get("lote_id", "").strip()
    tipo    = request.form.get("tipo",    "").strip()
    valor   = request.form.get("valor",   "").strip()
    fecha   = request.form.get("fecha",   "").strip()
    notas   = request.form.get("notas",   "").strip()

    if not all([lote_id, tipo, valor, fecha]):
        flash("Completa todos los campos obligatorios.", "error")
        return redirect("/produccion")

    try:
        lote_id = int(lote_id)
        valor   = round(float(valor), 2)
        if valor < 0:
            raise ValueError
    except ValueError:
        flash("Valor debe ser un número positivo.", "error")
        return redirect("/produccion")

    lote = sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}")
    if not lote:
        flash("Lote no encontrado.", "error")
        return redirect("/produccion")

    backup_automatico(owner_id)

    sb_post("produccion", {
        "usuario_id": owner_id,
        "lote_id":    lote_id,
        "tipo":       tipo,
        "valor":      valor,
        "fecha":      fecha,
        "notas":      notas,
    })

    flash("✅ Registro de producción guardado.", "success")
    return redirect(f"/produccion?lote_id={lote_id}")


# ================= ELIMINAR REGISTRO (solo admin) =================
@bp.route("/eliminar_produccion/<registro_id>", methods=["POST"])
@solo_admin
def eliminar_produccion(registro_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    reg = sb_get("produccion", f"id=eq.{registro_id}&usuario_id=eq.{owner_id}")
    if not reg:
        flash("Registro no encontrado.", "error")
        return redirect("/produccion")

    backup_automatico(owner_id)
    sb_delete("produccion", f"id=eq.{registro_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Registro eliminado.", "success")
    return redirect("/produccion")


# ================= API: datos gráfico por lote y tipo =================
@bp.route("/api/produccion/<lote_id>/<tipo>")
def api_produccion(lote_id, tipo):
    """Retorna datos de producción para un lote y tipo específico en JSON."""
    if "user_id" not in session:
        return jsonify([])

    owner_id, _ = get_granja_info(session["user_id"])

    datos = sb_get("produccion",
                   f"usuario_id=eq.{owner_id}"
                   f"&lote_id=eq.{lote_id}"
                   f"&tipo=eq.{tipo}"
                   f"&order=fecha.asc")

    return jsonify([{
        "fecha": d.get("fecha", ""),
        "valor": _fmt(d.get("valor", 0))
    } for d in datos])