# routes/animales.py
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin
import datetime

bp = Blueprint("animales", __name__)

ESTADOS = {
    "activo":   {"label": "Activo",   "emoji": "✅", "color": "#27ae60"},
    "vendido":  {"label": "Vendido",  "emoji": "💰", "color": "#3498db"},
    "muerto":   {"label": "Muerto",   "emoji": "💀", "color": "#e74c3c"},
    "descarte": {"label": "Descarte", "emoji": "🚫", "color": "#e67e22"},
    "donado":   {"label": "Donado",   "emoji": "🤝", "color": "#9b59b6"},
}


def _fmt(v):
    return round(float(v or 0), 2)


def _enriquecer(a, animales_idx, lotes_idx):
    a["estado_info"] = ESTADOS.get(a.get("estado", "activo"), ESTADOS["activo"])
    a["lote_nombre"] = lotes_idx.get(a.get("lote_id"), "Sin lote")
    madre = animales_idx.get(a.get("madre_id"), {})
    padre = animales_idx.get(a.get("padre_id"), {})
    a["madre_nombre"] = madre.get("nombre") or madre.get("arete") or "—"
    a["padre_nombre"] = padre.get("nombre") or padre.get("arete") or "—"
    if a.get("fecha_nacimiento"):
        try:
            dias = (datetime.date.today() -
                    datetime.date.fromisoformat(a["fecha_nacimiento"])).days
            if dias < 30:    a["edad_texto"] = f"{dias} días"
            elif dias < 365: a["edad_texto"] = f"{dias // 30} meses"
            else:            a["edad_texto"] = f"{dias // 365} año(s)"
        except Exception:    a["edad_texto"] = "—"
    else:
        a["edad_texto"] = "—"
    return a


@bp.route("/animales")
def animales():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, mi_rol  = get_granja_info(session["user_id"])
    filtro_lote   = request.args.get("lote_id", "")
    filtro_estado = request.args.get("estado",  "activo")
    filtro_texto  = request.args.get("q",       "").strip().lower()

    q = f"usuario_id=eq.{owner_id}"
    if filtro_lote:   q += f"&lote_id=eq.{filtro_lote}"
    if filtro_estado: q += f"&estado=eq.{filtro_estado}"

    todos        = sb_get("animales", q + "&order=created_at.desc")
    lotes        = sb_get("lotes",    f"usuario_id=eq.{owner_id}")
    todos_anim   = sb_get("animales", f"usuario_id=eq.{owner_id}")
    lotes_idx    = {l["id"]: l["nombre"] for l in lotes}
    animales_idx = {a["id"]: a           for a in todos_anim}

    if filtro_texto:
        todos = [a for a in todos if
                 filtro_texto in (a.get("arete")  or "").lower() or
                 filtro_texto in (a.get("nombre") or "").lower()]

    todos = [_enriquecer(a, animales_idx, lotes_idx) for a in todos]
    total_activos = sum(1 for a in todos_anim if a.get("estado") == "activo")
    total_hembras = sum(1 for a in todos_anim if a.get("estado") == "activo" and a.get("sexo") == "hembra")
    total_machos  = sum(1 for a in todos_anim if a.get("estado") == "activo" and a.get("sexo") == "macho")

    return render_template("animales.html",
        animales=todos, lotes=lotes, mi_rol=mi_rol,
        filtro_lote=filtro_lote, filtro_estado=filtro_estado,
        filtro_texto=filtro_texto, estados=ESTADOS,
        total_activos=total_activos, total_hembras=total_hembras, total_machos=total_machos)


@bp.route("/crear_animal", methods=["POST"])
@solo_admin
def crear_animal():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])

    lote_id          = request.form.get("lote_id",          "").strip() or None
    arete            = request.form.get("arete",            "").strip() or None
    nombre           = request.form.get("nombre",           "").strip() or None
    sexo             = request.form.get("sexo",    "desconocido").strip()
    tipo             = request.form.get("tipo",             "").strip()
    raza             = request.form.get("raza",             "").strip() or None
    fecha_nacimiento = request.form.get("fecha_nacimiento", "").strip() or None
    peso_inicial     = request.form.get("peso_inicial",     "").strip() or None
    madre_id         = request.form.get("madre_id",         "").strip() or None
    padre_id         = request.form.get("padre_id",         "").strip() or None
    notas            = request.form.get("notas",            "").strip() or None

    if not tipo:
        flash("El tipo de animal es obligatorio.", "error")
        return redirect("/animales")
    try:
        if lote_id:      lote_id      = int(lote_id)
        if madre_id:     madre_id     = int(madre_id)
        if padre_id:     padre_id     = int(padre_id)
        if peso_inicial: peso_inicial = round(float(peso_inicial), 2)
    except ValueError:
        flash("Valores numéricos inválidos.", "error")
        return redirect("/animales")

    if lote_id and not sb_get("lotes", f"id=eq.{lote_id}&usuario_id=eq.{owner_id}"):
        flash("Lote no encontrado.", "error")
        return redirect("/animales")

    backup_automatico(owner_id)
    sb_post("animales", {
        "usuario_id": owner_id, "lote_id": lote_id, "arete": arete, "nombre": nombre,
        "sexo": sexo, "tipo": tipo, "raza": raza, "fecha_nacimiento": fecha_nacimiento,
        "peso_inicial": peso_inicial, "madre_id": madre_id, "padre_id": padre_id,
        "estado": "activo", "notas": notas,
    })
    flash(f"✅ '{nombre or arete or 'Animal'}' registrado.", "success")
    return redirect("/animales")


@bp.route("/animal/<animal_id>")
def detalle_animal(animal_id):
    if "user_id" not in session:
        return redirect("/login")
    owner_id, mi_rol = get_granja_info(session["user_id"])
    animal = sb_get("animales", f"id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    if not animal:
        flash("Animal no encontrado.", "error")
        return redirect("/animales")

    a            = animal[0]
    lotes        = sb_get("lotes",    f"usuario_id=eq.{owner_id}")
    todos_anim   = sb_get("animales", f"usuario_id=eq.{owner_id}")
    lotes_idx    = {l["id"]: l["nombre"] for l in lotes}
    animales_idx = {x["id"]: x for x in todos_anim}
    a            = _enriquecer(a, animales_idx, lotes_idx)

    repro   = sb_get("reproduccion",
                     f"animal_id=eq.{animal_id}&usuario_id=eq.{owner_id}&order=fecha.desc")
    pesajes = sb_get("pesajes",
                     f"animal_id=eq.{animal_id}&usuario_id=eq.{owner_id}&order=fecha.asc")

    gdp = None
    if len(pesajes) >= 2:
        try:
            d1 = datetime.date.fromisoformat(pesajes[0]["fecha"])
            d2 = datetime.date.fromisoformat(pesajes[-1]["fecha"])
            dias = (d2 - d1).days
            if dias > 0:
                gdp = round((_fmt(pesajes[-1]["peso_kg"]) - _fmt(pesajes[0]["peso_kg"])) / dias, 3)
        except Exception:
            pass

    crias  = sb_get("animales", f"madre_id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    crias += sb_get("animales", f"padre_id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    hembras = [x for x in todos_anim if x.get("sexo") == "hembra" and x["id"] != a["id"]]
    machos  = [x for x in todos_anim if x.get("sexo") == "macho"  and x["id"] != a["id"]]

    return render_template("detalle_animal.html",
        animal=a, lotes=lotes, repro=repro, pesajes=pesajes,
        gdp=gdp, crias=crias, hembras=hembras, machos=machos,
        mi_rol=mi_rol, estados=ESTADOS)


@bp.route("/editar_animal/<animal_id>", methods=["POST"])
@solo_admin
def editar_animal(animal_id):
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    if not sb_get("animales", f"id=eq.{animal_id}&usuario_id=eq.{owner_id}"):
        flash("Animal no encontrado.", "error")
        return redirect("/animales")

    lote_id = request.form.get("lote_id",  "").strip() or None
    madre_id = request.form.get("madre_id", "").strip() or None
    padre_id = request.form.get("padre_id", "").strip() or None
    try:
        if lote_id:  lote_id  = int(lote_id)
        if madre_id: madre_id = int(madre_id)
        if padre_id: padre_id = int(padre_id)
    except ValueError:
        flash("Valores inválidos.", "error")
        return redirect(f"/animal/{animal_id}")

    sb_patch("animales", f"id=eq.{animal_id}&usuario_id=eq.{owner_id}", {
        "arete": request.form.get("arete", "").strip() or None,
        "nombre": request.form.get("nombre", "").strip() or None,
        "estado": request.form.get("estado", "activo"),
        "lote_id": lote_id, "madre_id": madre_id, "padre_id": padre_id,
        "notas": request.form.get("notas", "").strip() or None,
    })
    flash("✅ Animal actualizado.", "success")
    return redirect(f"/animal/{animal_id}")


@bp.route("/eliminar_animal/<animal_id>", methods=["POST"])
@solo_admin
def eliminar_animal(animal_id):
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    if not sb_get("animales", f"id=eq.{animal_id}&usuario_id=eq.{owner_id}"):
        flash("Animal no encontrado.", "error")
        return redirect("/animales")
    backup_automatico(owner_id)
    sb_delete("pesajes",      f"animal_id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    sb_delete("reproduccion", f"animal_id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    sb_delete("animales",     f"id=eq.{animal_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Animal eliminado.", "success")
    return redirect("/animales")


@bp.route("/api/animales_buscar")
def api_buscar():
    if "user_id" not in session:
        return jsonify([])
    owner_id, _ = get_granja_info(session["user_id"])
    q    = request.args.get("q",    "").strip().lower()
    sexo = request.args.get("sexo", "")
    filtro = f"usuario_id=eq.{owner_id}&estado=eq.activo"
    if sexo: filtro += f"&sexo=eq.{sexo}"
    todos = sb_get("animales", filtro)
    if q:
        todos = [a for a in todos if
                 q in (a.get("arete") or "").lower() or
                 q in (a.get("nombre") or "").lower()]
    return jsonify([{
        "id": a["id"],
        "label": (f"{a.get('arete','')} {a.get('nombre','')}".strip()) or f"ID {a['id']}",
        "sexo": a.get("sexo"),
    } for a in todos[:20]])