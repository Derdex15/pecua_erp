# routes/pesajes.py
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_delete, enc
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin, es_premium_owner
import datetime

bp = Blueprint("pesajes", __name__)


def _fmt(v):
    return round(float(v or 0), 2)


def _calcular_gdp(lista_pesajes):
    """Ganancia Diaria de Peso entre el primer y último pesaje de una lista ordenada por fecha."""
    if len(lista_pesajes) < 2:
        return None
    try:
        d1   = datetime.date.fromisoformat(lista_pesajes[0]["fecha"])
        d2   = datetime.date.fromisoformat(lista_pesajes[-1]["fecha"])
        dias = (d2 - d1).days
        if dias <= 0:
            return None
        return round((_fmt(lista_pesajes[-1]["peso_kg"]) -
                      _fmt(lista_pesajes[0]["peso_kg"])) / dias, 3)
    except Exception:
        return None


@bp.route("/pesajes")
def pesajes():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    if not es_premium_owner(session["user_id"]):
        return render_template("premium_requerido.html", funcion="Pesajes y GDP")
    filtro_tipo = request.args.get("tipo", "lote")  # "lote" o "animal"
    filtro_id   = request.args.get("ref_id", "")

    lotes   = sb_get("lotes",    f"usuario_id=eq.{owner_id}&activo=eq.true")
    animales = sb_get("animales", f"usuario_id=eq.{owner_id}&estado=eq.activo")

    # Pesajes filtrados
    q = f"usuario_id=eq.{owner_id}&order=fecha.asc"
    if filtro_tipo == "animal" and filtro_id:
        q_pesajes = f"usuario_id=eq.{owner_id}&animal_id=eq.{enc(filtro_id)}&order=fecha.asc"
    elif filtro_tipo == "lote" and filtro_id:
        q_pesajes = f"usuario_id=eq.{owner_id}&lote_id=eq.{enc(filtro_id)}&order=fecha.asc"
    else:
        q_pesajes = f"usuario_id=eq.{owner_id}&order=fecha.desc"

    todos_pesajes = sb_get("pesajes", q_pesajes)

    # Enriquecer con nombre
    todos_lotes  = sb_get("lotes",    f"usuario_id=eq.{owner_id}")
    todos_anim   = sb_get("animales", f"usuario_id=eq.{owner_id}")
    lotes_idx    = {l["id"]: l["nombre"] for l in todos_lotes}
    animales_idx = {a["id"]: a           for a in todos_anim}

    for p in todos_pesajes:
        if p.get("animal_id"):
            a = animales_idx.get(p["animal_id"], {})
            p["referencia"] = a.get("nombre") or a.get("arete") or f"Animal {p['animal_id']}"
            p["tipo_ref"]   = "animal"
        else:
            p["referencia"] = lotes_idx.get(p.get("lote_id"), "Desconocido")
            p["tipo_ref"]   = "lote"
        p["peso_kg"] = _fmt(p.get("peso_kg", 0))

    # GDP de la selección actual
    gdp_actual = None
    if filtro_id:
        ordenados = sorted(todos_pesajes, key=lambda x: x.get("fecha", ""))
        gdp_actual = _calcular_gdp(ordenados)

    return render_template("pesajes.html",
        lotes=lotes, animales=animales,
        pesajes=todos_pesajes, mi_rol=mi_rol,
        filtro_tipo=filtro_tipo, filtro_id=filtro_id,
        gdp_actual=gdp_actual)


@bp.route("/registrar_pesaje", methods=["POST"])
def registrar_pesaje():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    tipo_ref = request.form.get("tipo_ref", "lote").strip()
    ref_id   = request.form.get("ref_id",   "").strip()
    peso_kg  = request.form.get("peso_kg",  "").strip()
    fecha    = request.form.get("fecha",    "").strip()
    notas    = request.form.get("notas",    "").strip() or None

    if not all([ref_id, peso_kg, fecha]):
        flash("Referencia, peso y fecha son obligatorios.", "error")
        return redirect("/pesajes")

    try:
        ref_id  = int(ref_id)
        peso_kg = round(float(peso_kg), 2)
        if peso_kg <= 0:
            raise ValueError
    except ValueError:
        flash("Peso debe ser un número positivo.", "error")
        return redirect("/pesajes")

    animal_id = None
    lote_id   = None

    if tipo_ref == "animal":
        if not sb_get("animales", f"id=eq.{ref_id}&usuario_id=eq.{owner_id}"):
            flash("Animal no encontrado.", "error")
            return redirect("/pesajes")
        animal_id = ref_id
    else:
        if not sb_get("lotes", f"id=eq.{ref_id}&usuario_id=eq.{owner_id}"):
            flash("Lote no encontrado.", "error")
            return redirect("/pesajes")
        lote_id = ref_id

    backup_automatico(owner_id)
    sb_post("pesajes", {
        "usuario_id": owner_id,
        "animal_id":  animal_id,
        "lote_id":    lote_id,
        "peso_kg":    peso_kg,
        "fecha":      fecha,
        "notas":      notas,
    })
    flash(f"✅ Pesaje de {peso_kg} kg registrado.", "success")
    return redirect(f"/pesajes?tipo={tipo_ref}&ref_id={ref_id}")


@bp.route("/eliminar_pesaje/<pesaje_id>", methods=["POST"])
@solo_admin
def eliminar_pesaje(pesaje_id):
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    if not sb_get("pesajes", f"id=eq.{pesaje_id}&usuario_id=eq.{owner_id}"):
        flash("Pesaje no encontrado.", "error")
        return redirect("/pesajes")
    sb_delete("pesajes", f"id=eq.{pesaje_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Pesaje eliminado.", "success")
    return redirect("/pesajes")


@bp.route("/api/pesajes/<tipo_ref>/<ref_id>")
def api_pesajes(tipo_ref, ref_id):
    """Retorna lista de pesajes para gráfico en JSON."""
    if "user_id" not in session:
        return jsonify([])
    owner_id, _ = get_granja_info(session["user_id"])
    if tipo_ref == "animal":
        datos = sb_get("pesajes",
                       f"animal_id=eq.{ref_id}&usuario_id=eq.{owner_id}&order=fecha.asc")
    else:
        datos = sb_get("pesajes",
                       f"lote_id=eq.{ref_id}&usuario_id=eq.{owner_id}&order=fecha.asc")
    return jsonify([{
        "fecha":   d.get("fecha", ""),
        "peso_kg": _fmt(d.get("peso_kg", 0)),
    } for d in datos])