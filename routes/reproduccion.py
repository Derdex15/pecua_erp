# routes/reproduccion.py
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin, es_premium_owner
import datetime

bp = Blueprint("reproduccion", __name__)

GESTACION_DIAS = {
    "vaca": 283, "cerdo": 114, "cabra": 150,
    "oveja": 147, "yegua": 336, "burra": 365,
}
GESTACION_DEFAULT = 280

TIPOS_REPRO = {
    "celo":              {"label": "Celo detectado",    "emoji": "🔴", "color": "#e74c3c"},
    "monta":             {"label": "Monta natural",     "emoji": "🐄", "color": "#8e44ad"},
    "inseminacion":      {"label": "Inseminación",      "emoji": "💉", "color": "#3498db"},
    "prenez_confirmada": {"label": "Preñez confirmada", "emoji": "✅", "color": "#27ae60"},
    "aborto":            {"label": "Aborto",            "emoji": "⚠️", "color": "#e67e22"},
    "parto":             {"label": "Parto",             "emoji": "🐣", "color": "#f39c12"},
}


def _fecha_parto(tipo_animal, fecha_monta):
    dias = GESTACION_DIAS.get((tipo_animal or "").lower(), GESTACION_DEFAULT)
    try:
        return str(datetime.date.fromisoformat(fecha_monta) + datetime.timedelta(days=dias))
    except Exception:
        return None


@bp.route("/reproduccion")
def reproduccion():
    if "user_id" not in session:
        return redirect("/login")
    user_id = session["user_id"]
    if not es_premium_owner(user_id):
        return render_template("premium_requerido.html", funcion="Control Reproductivo")

    owner_id, mi_rol = get_granja_info(user_id)
    hembras  = sb_get("animales", f"usuario_id=eq.{owner_id}&sexo=eq.hembra&estado=eq.activo")
    machos   = sb_get("animales", f"usuario_id=eq.{owner_id}&sexo=eq.macho&estado=eq.activo")
    registros = sb_get("reproduccion", f"usuario_id=eq.{owner_id}&order=fecha.desc")

    todos_anim   = sb_get("animales", f"usuario_id=eq.{owner_id}")
    animales_idx = {a["id"]: a for a in todos_anim}

    hoy = datetime.date.today()
    for r in registros:
        a = animales_idx.get(r.get("animal_id"), {})
        r["animal_label"] = a.get("nombre") or a.get("arete") or f"ID {r['animal_id']}"
        r["tipo_info"] = TIPOS_REPRO.get(r.get("tipo", ""), {"label": r.get("tipo",""), "emoji": "❓", "color": "#95a5a6"})
        if r.get("fecha_esperada"):
            try:
                r["dias_esperado"] = (datetime.date.fromisoformat(r["fecha_esperada"]) - hoy).days
            except Exception:
                r["dias_esperado"] = None

    anio_actual = str(hoy.year)
    partos_anio = sum(1 for r in registros if r.get("tipo") == "parto" and (r.get("fecha") or "")[:4] == anio_actual)
    prenadas    = sum(1 for r in registros if r.get("tipo") == "prenez_confirmada" and r.get("resultado") == "en_curso")

    return render_template("reproduccion.html",
        hembras=hembras, machos=machos, registros=registros,
        mi_rol=mi_rol, tipos=TIPOS_REPRO,
        partos_anio=partos_anio, prenadas=prenadas)


@bp.route("/registrar_repro", methods=["POST"])
def registrar_repro():
    if "user_id" not in session:
        return redirect("/login")
    user_id = session["user_id"]
    if not es_premium_owner(user_id):
        return redirect("/reproduccion")

    owner_id, _ = get_granja_info(user_id)
    animal_id   = request.form.get("animal_id",     "").strip()
    tipo        = request.form.get("tipo",          "").strip()
    fecha       = request.form.get("fecha",         "").strip()
    padre_id    = request.form.get("padre_id",      "").strip() or None
    crias_nac   = request.form.get("crias_nacidas", "").strip() or None
    crias_vivas = request.form.get("crias_vivas",   "").strip() or None
    notas       = request.form.get("notas",         "").strip() or None
    resultado   = request.form.get("resultado",     "en_curso").strip()

    if not all([animal_id, tipo, fecha]):
        flash("Animal, tipo y fecha son obligatorios.", "error")
        return redirect("/reproduccion")
    if tipo not in TIPOS_REPRO:
        flash("Tipo inválido.", "error")
        return redirect("/reproduccion")

    try:
        animal_id = int(animal_id)
        if padre_id:    padre_id    = int(padre_id)
        if crias_nac:   crias_nac   = int(crias_nac)
        if crias_vivas: crias_vivas = int(crias_vivas)
    except ValueError:
        flash("Valores inválidos.", "error")
        return redirect("/reproduccion")

    animal = sb_get("animales", f"id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    if not animal:
        flash("Animal no encontrado.", "error")
        return redirect("/reproduccion")

    a = animal[0]
    fecha_esperada = None

    if tipo in ("monta", "inseminacion"):
        fecha_esperada = _fecha_parto(a.get("tipo", ""), fecha)
        resultado = "en_curso"

    if tipo == "parto":
        # Cerrar preñeces abiertas de este animal
        prenez = sb_get("reproduccion",
                        f"animal_id=eq.{animal_id}&usuario_id=eq.{owner_id}"
                        f"&tipo=eq.prenez_confirmada&resultado=eq.en_curso")
        for p in prenez:
            sb_patch("reproduccion", f"id=eq.{p['id']}&usuario_id=eq.{owner_id}",
                     {"resultado": "exitoso"})
        resultado = "exitoso"

    backup_automatico(owner_id)
    sb_post("reproduccion", {
        "usuario_id": owner_id, "animal_id": animal_id,
        "tipo": tipo, "fecha": fecha, "padre_id": padre_id,
        "crias_nacidas": crias_nac, "crias_vivas": crias_vivas,
        "fecha_esperada": fecha_esperada,
        "resultado": resultado, "notas": notas,
    })

    # Alerta automática de parto
    if fecha_esperada:
        label = a.get("nombre") or a.get("arete") or f"animal {animal_id}"
        sb_post("alertas", {
            "usuario_id":   owner_id,
            "lote_id":      None,
            "tipo":         "parto_esperado",
            "mensaje":      f"🐣 Parto esperado de {label} el {fecha_esperada}",
            "fecha_alerta": str(datetime.date.today()),
            "leida":        False,
        })

    msg = f"✅ {TIPOS_REPRO[tipo]['label']} registrado."
    if fecha_esperada:
        msg += f" Parto estimado: {fecha_esperada}."
    flash(msg, "success")
    return redirect("/reproduccion")


@bp.route("/eliminar_repro/<repro_id>", methods=["POST"])
@solo_admin
def eliminar_repro(repro_id):
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    if not sb_get("reproduccion", f"id=eq.{repro_id}&usuario_id=eq.{owner_id}"):
        flash("Registro no encontrado.", "error")
        return redirect("/reproduccion")
    backup_automatico(owner_id)
    sb_delete("reproduccion", f"id=eq.{repro_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Registro eliminado.", "success")
    return redirect("/reproduccion")


@bp.route("/api/gestacion/<tipo_animal>")
def api_gestacion(tipo_animal):
    dias = GESTACION_DIAS.get(tipo_animal.lower(), GESTACION_DEFAULT)
    return jsonify({"dias": dias})