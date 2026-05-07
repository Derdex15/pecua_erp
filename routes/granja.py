from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from werkzeug.security import generate_password_hash
import datetime

bp = Blueprint("granja", __name__)


def es_premium(user_id):
    hoy = str(datetime.date.today())
    res = sb_get("suscripciones",
                 f"usuario_id=eq.{user_id}&plan=eq.premium&activa=eq.true&fecha_fin=gte.{hoy}")
    return bool(res)


def get_granja_usuario(user_id):
    """Retorna la granja donde el usuario es owner o miembro activo."""
    # Buscar si es owner
    granja = sb_get("granjas", f"owner_id=eq.{user_id}")
    if granja:
        return granja[0], "admin"

    # Buscar si es miembro
    membresia = sb_get("granja_miembros",
                       f"usuario_id=eq.{user_id}&activo=eq.true")
    if membresia:
        granja = sb_get("granjas", f"id=eq.{membresia[0]['granja_id']}")
        if granja:
            return granja[0], membresia[0].get("rol", "operador")

    return None, None


def get_owner_id(user_id):
    """Dado un user_id, retorna el owner_id de su granja (para filtrar datos compartidos)."""
    granja, rol = get_granja_usuario(user_id)
    if not granja:
        return user_id  # Sin granja: solo sus propios datos
    return granja["owner_id"]


# ================= GESTIÓN DE GRANJA =================
@bp.route("/granja")
def granja():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if not es_premium(user_id):
        return render_template("premium_requerido.html", funcion="Múltiples Usuarios")

    mi_granja, mi_rol = get_granja_usuario(user_id)
    miembros = []

    if mi_granja:
        miembros_raw = sb_get("granja_miembros",
                              f"granja_id=eq.{mi_granja['id']}&activo=eq.true")
        # Enriquecer con datos del usuario
        for m in miembros_raw:
            usuario = sb_get("usuarios", f"id=eq.{m['usuario_id']}")
            m["username"] = usuario[0]["username"] if usuario else "Desconocido"
        miembros = miembros_raw

    return render_template(
        "granja.html",
        granja=mi_granja,
        mi_rol=mi_rol,
        miembros=miembros,
        user_id=user_id,
    )


# ================= CREAR GRANJA =================
@bp.route("/crear_granja", methods=["POST"])
def crear_granja():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if not es_premium(user_id):
        return redirect("/granja")

    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre de la granja es obligatorio.", "error")
        return redirect("/granja")

    # Verificar que no tenga ya una granja
    existente = sb_get("granjas", f"owner_id=eq.{user_id}")
    if existente:
        flash("Ya tienes una granja creada.", "error")
        return redirect("/granja")

    nueva = sb_post("granjas", {
        "owner_id": user_id,
        "nombre":   nombre,
    }, prefer_representation=True)

    if nueva:
        # El owner también es miembro admin
        sb_post("granja_miembros", {
            "granja_id":  nueva[0]["id"],
            "usuario_id": user_id,
            "rol":        "admin",
            "activo":     True,
        })
        flash(f"✅ Granja '{nombre}' creada correctamente.", "success")
    else:
        flash("Error al crear la granja.", "error")

    return redirect("/granja")


# ================= INVITAR USUARIO =================
@bp.route("/invitar_usuario", methods=["POST"])
def invitar_usuario():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if not es_premium(user_id):
        return redirect("/granja")

    # Solo el admin/owner puede invitar
    mi_granja, mi_rol = get_granja_usuario(user_id)
    if not mi_granja or mi_rol != "admin":
        flash("Solo el administrador puede invitar usuarios.", "error")
        return redirect("/granja")

    username_nuevo = request.form.get("username", "").strip()
    rol_nuevo      = request.form.get("rol", "operador").strip()

    if not username_nuevo:
        flash("Ingresa el nombre de usuario a invitar.", "error")
        return redirect("/granja")

    # Buscar el usuario por username
    usuario_nuevo = sb_get("usuarios", f"username=eq.{username_nuevo}")
    if not usuario_nuevo:
        flash(f"El usuario '{username_nuevo}' no existe. Debe crear una cuenta primero.", "error")
        return redirect("/granja")

    nuevo_id = usuario_nuevo[0]["id"]

    # Verificar que no sea el mismo owner
    if nuevo_id == user_id:
        flash("No puedes agregarte a ti mismo.", "error")
        return redirect("/granja")

    # Verificar que no sea ya miembro
    ya_miembro = sb_get("granja_miembros",
                        f"granja_id=eq.{mi_granja['id']}&usuario_id=eq.{nuevo_id}")
    if ya_miembro:
        if ya_miembro[0].get("activo"):
            flash(f"'{username_nuevo}' ya es miembro de tu granja.", "error")
        else:
            # Reactivar miembro anterior
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


# ================= CAMBIAR ROL =================
@bp.route("/cambiar_rol/<miembro_id>", methods=["POST"])
def cambiar_rol(miembro_id):
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    mi_granja, mi_rol = get_granja_usuario(user_id)
    if not mi_granja or mi_rol != "admin":
        flash("Sin permisos.", "error")
        return redirect("/granja")

    nuevo_rol = request.form.get("rol", "operador")
    sb_patch("granja_miembros",
             f"id=eq.{miembro_id}&granja_id=eq.{mi_granja['id']}",
             {"rol": nuevo_rol})
    flash("✅ Rol actualizado.", "success")
    return redirect("/granja")


# ================= REMOVER USUARIO =================
@bp.route("/remover_usuario/<miembro_id>", methods=["POST"])
def remover_usuario(miembro_id):
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    mi_granja, mi_rol = get_granja_usuario(user_id)
    if not mi_granja or mi_rol != "admin":
        flash("Sin permisos.", "error")
        return redirect("/granja")

    sb_patch("granja_miembros",
             f"id=eq.{miembro_id}&granja_id=eq.{mi_granja['id']}",
             {"activo": False})
    flash("🗑 Usuario removido de la granja.", "success")
    return redirect("/granja")


# ================= API: info de granja actual =================
@bp.route("/api/mi_granja")
def api_mi_granja():
    from flask import jsonify
    if "user_id" not in session:
        return jsonify({"granja": None, "rol": None})

    granja, rol = get_granja_usuario(session["user_id"])
    if granja:
        return jsonify({"granja": granja["nombre"], "rol": rol})
    return jsonify({"granja": None, "rol": None})