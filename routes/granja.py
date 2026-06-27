# routes/granja.py
"""
Gestión de granjas y miembros — ERP Pecuario

Cambios respecto a la versión anterior:
  - Eliminadas es_premium() y get_owner_id() locales.
    Ahora se usan es_premium_owner() y get_granja_info() de permisos.py.
  - _get_granja_obj() es el único helper local: retorna el diccionario
    completo de la granja (nombre, id, owner_id) que los templates necesitan.
  - Corregido N+1: los usernames de miembros se obtienen en 1 sola query.
"""
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_post, sb_patch, enc
from routes.permisos import get_granja_info, es_premium_owner

bp = Blueprint("granja", __name__)


# ── Helper local ──────────────────────────────────────────────────────────────
def _get_granja_obj(user_id):
    """
    Retorna (granja_dict | None, rol_str).
    Devuelve el objeto completo de la granja para los templates.
    Para permisos y owner_id usa get_granja_info() de permisos.py.
    """
    granja = sb_get("granjas", f"owner_id=eq.{user_id}")
    if granja:
        return granja[0], "admin"

    membresia = sb_get("granja_miembros", f"usuario_id=eq.{user_id}&activo=eq.true")
    if membresia:
        g = sb_get("granjas", f"id=eq.{membresia[0]['granja_id']}")
        if g:
            return g[0], membresia[0].get("rol", "operador")

    return None, None


# ── Vista principal ────────────────────────────────────────────────────────────
@bp.route("/granja")
def granja():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if not es_premium_owner(user_id):
        return render_template("premium_requerido.html", funcion="Múltiples Usuarios")

    mi_granja, mi_rol = _get_granja_obj(user_id)
    miembros = []

    if mi_granja:
        miembros_raw = sb_get("granja_miembros",
                              f"granja_id=eq.{mi_granja['id']}&activo=eq.true")

        # Fix N+1: una sola query para obtener todos los usernames
        if miembros_raw:
            user_ids     = ",".join(str(m["usuario_id"]) for m in miembros_raw)
            usuarios     = sb_get("usuarios", f"id=in.({user_ids})")
            usuarios_idx = {u["id"]: u.get("username", "Desconocido") for u in usuarios}
            for m in miembros_raw:
                m["username"] = usuarios_idx.get(m["usuario_id"], "Desconocido")

        miembros = miembros_raw

    return render_template(
        "granja.html",
        granja=mi_granja,
        mi_rol=mi_rol,
        miembros=miembros,
        user_id=user_id,
    )


# ── Crear granja ───────────────────────────────────────────────────────────────
@bp.route("/crear_granja", methods=["POST"])
def crear_granja():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if not es_premium_owner(user_id):
        return redirect("/granja")

    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre de la granja es obligatorio.", "error")
        return redirect("/granja")

    if sb_get("granjas", f"owner_id=eq.{user_id}"):
        flash("Ya tienes una granja creada.", "error")
        return redirect("/granja")

    nueva = sb_post("granjas", {"owner_id": user_id, "nombre": nombre},
                    prefer_representation=True)
    if nueva:
        sb_post("granja_miembros", {
            "granja_id":  nueva[0]["id"],
            "usuario_id": user_id,
            "rol":        "admin",
            "activo":     True,
        })
        flash(f"✅ Granja '{nombre}' creada correctamente.", "success")
    else:
        flash("Error al crear la granja. Intenta de nuevo.", "error")

    return redirect("/granja")


# ── Invitar usuario ────────────────────────────────────────────────────────────
@bp.route("/invitar_usuario", methods=["POST"])
def invitar_usuario():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if not es_premium_owner(user_id):
        return redirect("/granja")

    mi_granja, mi_rol = _get_granja_obj(user_id)
    if not mi_granja or mi_rol != "admin":
        flash("Solo el administrador puede invitar usuarios.", "error")
        return redirect("/granja")

    username_nuevo = request.form.get("username", "").strip()
    rol_nuevo      = request.form.get("rol", "operador").strip()

    if not username_nuevo:
        flash("Ingresa el nombre de usuario a invitar.", "error")
        return redirect("/granja")

    usuario_nuevo = sb_get("usuarios", f"username=eq.{enc(username_nuevo)}")
    if not usuario_nuevo:
        flash(f"El usuario '{username_nuevo}' no existe. "
              f"Debe crear una cuenta primero.", "error")
        return redirect("/granja")

    nuevo_id = usuario_nuevo[0]["id"]

    if nuevo_id == user_id:
        flash("No puedes agregarte a ti mismo.", "error")
        return redirect("/granja")

    ya_miembro = sb_get("granja_miembros",
                        f"granja_id=eq.{mi_granja['id']}&usuario_id=eq.{nuevo_id}")
    if ya_miembro:
        if ya_miembro[0].get("activo"):
            flash(f"'{username_nuevo}' ya es miembro de tu granja.", "error")
        else:
            sb_patch("granja_miembros",
                     f"granja_id=eq.{mi_granja['id']}&usuario_id=eq.{nuevo_id}",
                     {"activo": True, "rol": rol_nuevo})
            flash(f"✅ '{username_nuevo}' reactivado con rol {rol_nuevo}.", "success")
        return redirect("/granja")

    sb_post("granja_miembros", {
        "granja_id":  mi_granja["id"],
        "usuario_id": nuevo_id,
        "rol":        rol_nuevo,
        "activo":     True,
    })
    flash(f"✅ '{username_nuevo}' agregado como {rol_nuevo}.", "success")
    return redirect("/granja")


# ── Cambiar rol ────────────────────────────────────────────────────────────────
@bp.route("/cambiar_rol/<miembro_id>", methods=["POST"])
def cambiar_rol(miembro_id):
    if "user_id" not in session:
        return redirect("/login")

    mi_granja, mi_rol = _get_granja_obj(session["user_id"])
    if not mi_granja or mi_rol != "admin":
        flash("Sin permisos.", "error")
        return redirect("/granja")

    nuevo_rol = request.form.get("rol", "operador")
    sb_patch("granja_miembros",
             f"id=eq.{miembro_id}&granja_id=eq.{mi_granja['id']}",
             {"rol": nuevo_rol})
    flash("✅ Rol actualizado.", "success")
    return redirect("/granja")


# ── Remover usuario ────────────────────────────────────────────────────────────
@bp.route("/remover_usuario/<miembro_id>", methods=["POST"])
def remover_usuario(miembro_id):
    if "user_id" not in session:
        return redirect("/login")

    mi_granja, mi_rol = _get_granja_obj(session["user_id"])
    if not mi_granja or mi_rol != "admin":
        flash("Sin permisos.", "error")
        return redirect("/granja")

    sb_patch("granja_miembros",
             f"id=eq.{miembro_id}&granja_id=eq.{mi_granja['id']}",
             {"activo": False})
    flash("🗑 Usuario removido de la granja.", "success")
    return redirect("/granja")


# ── API: info de granja actual ─────────────────────────────────────────────────
@bp.route("/api/mi_granja")
def api_mi_granja():
    if "user_id" not in session:
        return jsonify({"granja": None, "rol": None})

    granja, rol = _get_granja_obj(session["user_id"])
    if granja:
        return jsonify({"granja": granja["nombre"], "rol": rol})
    return jsonify({"granja": None, "rol": None})