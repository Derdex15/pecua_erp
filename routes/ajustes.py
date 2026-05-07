# routes/ajustes.py
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_delete, sb_patch
from backup_utils import hacer_backup
from routes.permisos import get_granja_info, solo_admin, es_premium_owner
import datetime

bp = Blueprint("ajustes", __name__)


# ================= AJUSTES =================
@bp.route("/ajustes")
def ajustes():
    if "user_id" not in session:
        return redirect("/login")

    _, mi_rol = get_granja_info(session["user_id"])
    return render_template("ajustes.html", mi_rol=mi_rol)


# ================= CAMBIAR CONTRASEÑA (cualquier usuario) =================
@bp.route("/cambiar_password", methods=["GET", "POST"])
def cambiar_password():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        from werkzeug.security import generate_password_hash, check_password_hash

        actual    = request.form.get("password_actual", "").strip()
        nueva     = request.form.get("password",        "").strip()
        confirmar = request.form.get("confirmar",       "").strip()

        # Cada usuario cambia SU propia contraseña (no la del owner)
        usuario = sb_get("usuarios", f"id=eq.{session['user_id']}")
        if not usuario or not check_password_hash(usuario[0]["password"], actual):
            return render_template("cambiar_password.html",
                                   error="La contraseña actual es incorrecta.")
        if len(nueva) < 6:
            return render_template("cambiar_password.html",
                                   error="La nueva contraseña debe tener al menos 6 caracteres.")
        if nueva != confirmar:
            return render_template("cambiar_password.html",
                                   error="Las contraseñas nuevas no coinciden.")

        sb_patch("usuarios", f"id=eq.{session['user_id']}", {
            "password": generate_password_hash(nueva)
        })
        flash("✅ Contraseña actualizada correctamente.", "success")
        return redirect("/ajustes")

    return render_template("cambiar_password.html")


# ================= BACKUP MANUAL (solo admin) =================
@bp.route("/backup", methods=["POST"])
@solo_admin
def backup():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    etiqueta = request.form.get("etiqueta", "").strip()
    hacer_backup(owner_id, etiqueta=etiqueta)
    flash("📦 Respaldo creado correctamente.", "success")
    return redirect("/ajustes")


# ================= VER BACKUPS (solo admin) =================
@bp.route("/backups")
@solo_admin
def ver_backups():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    premium = es_premium_owner(session["user_id"])

    backups = sb_get("respaldo", f"usuario_id=eq.{owner_id}&order=fecha.desc")

    # Plan gratuito: solo últimos 3
    if not premium:
        backups = backups[:3]

    return render_template("backups.html",
                           backups=backups,
                           es_premium=premium,
                           total=len(sb_get("respaldo", f"usuario_id=eq.{owner_id}")))


# ================= ELIMINAR BACKUP (solo admin) =================
@bp.route("/eliminar_backup/<backup_id>", methods=["POST"])
@solo_admin
def eliminar_backup(backup_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    sb_delete("respaldo", f"id=eq.{backup_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Backup eliminado.", "success")
    return redirect("/backups")


# ================= RESET (solo admin) =================
@bp.route("/reset", methods=["POST"])
@solo_admin
def reset():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    try:
        hacer_backup(owner_id, etiqueta="Antes del reinicio")
    except Exception as e:
        flash(f"❌ Error al hacer backup: {e}", "error")
        return redirect("/ajustes")

    sb_delete("gastos",     f"usuario_id=eq.{owner_id}")
    sb_delete("ventas",     f"usuario_id=eq.{owner_id}")
    sb_delete("lotes",      f"usuario_id=eq.{owner_id}")
    sb_delete("sanitario",  f"usuario_id=eq.{owner_id}")
    sb_delete("produccion", f"usuario_id=eq.{owner_id}")
    sb_delete("alertas",    f"usuario_id=eq.{owner_id}")

    flash("🗑 Todos los datos fueron eliminados. Se creó un respaldo previo.", "success")
    return redirect("/")


# ================= RESTAURAR (solo admin) =================
@bp.route("/restaurar/<backup_id>")
@solo_admin
def restaurar(backup_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _  = get_granja_info(session["user_id"])
    backup_data  = sb_get("respaldo", f"id=eq.{backup_id}&usuario_id=eq.{owner_id}")
    if not backup_data:
        flash("Backup no encontrado.", "error")
        return redirect("/backups")

    datos = backup_data[0].get("datos", {})

    sb_delete("gastos", f"usuario_id=eq.{owner_id}")
    sb_delete("ventas", f"usuario_id=eq.{owner_id}")
    sb_delete("lotes",  f"usuario_id=eq.{owner_id}")

    id_map = {}
    for lote in datos.get("lotes", []):
        old_id = lote.get("id")
        lote.pop("id", None)
        lote["usuario_id"] = owner_id
        nuevo = sb_post("lotes", lote, prefer_representation=True)
        if nuevo:
            id_map[old_id] = nuevo[0]["id"]

    for tabla in ["ventas", "gastos"]:
        for item in datos.get(tabla, []):
            item.pop("id", None)
            item["lote_id"]    = id_map.get(item.get("lote_id"))
            item["usuario_id"] = owner_id
            sb_post(tabla, item)

    flash("✅ Datos restaurados desde el respaldo.", "success")
    return redirect("/")