# routes/ajustes.py
"""
Ajustes — ERP Pecuario

CORRECCIONES vs versión anterior:
  - reset():     ahora elimina las 10 tablas (antes solo 5)
  - restaurar(): ahora reconstruye las 10 tablas del backup (antes solo 3)
"""
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import hacer_backup
from routes.permisos import get_granja_info, solo_admin, es_premium_owner

bp = Blueprint("ajustes", __name__)

# Tablas que se respaldan, resetean y restauran (mismo orden)
TABLAS_DATOS = [
    "lotes", "ventas", "gastos", "sanitario", "produccion",
    "animales", "reproduccion", "pesajes", "bajas", "insumos",
]


# ── Ajustes ────────────────────────────────────────────────────────────────────
@bp.route("/ajustes")
def ajustes():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    premium          = es_premium_owner(session["user_id"])

    return render_template("ajustes.html", mi_rol=mi_rol, es_premium=premium)


# ── Cambiar contraseña ─────────────────────────────────────────────────────────
@bp.route("/cambiar_password", methods=["GET", "POST"])
def cambiar_password():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "GET":
        return render_template("cambiar_password.html")

    from werkzeug.security import generate_password_hash, check_password_hash

    user_id      = session["user_id"]
    actual       = request.form.get("actual",       "").strip()
    nueva        = request.form.get("nueva",        "").strip()
    confirmacion = request.form.get("confirmacion", "").strip()

    if not all([actual, nueva, confirmacion]):
        flash("Completa todos los campos.", "error")
        return redirect("/cambiar_password")

    if nueva != confirmacion:
        flash("Las contraseñas nuevas no coinciden.", "error")
        return redirect("/cambiar_password")

    if len(nueva) < 8:
        flash("La contraseña debe tener al menos 8 caracteres.", "error")
        return redirect("/cambiar_password")

    usuario = sb_get("usuarios", f"id=eq.{user_id}")
    if not usuario or not check_password_hash(usuario[0].get("password", ""), actual):
        flash("Contraseña actual incorrecta.", "error")
        return redirect("/cambiar_password")

    nuevo_hash = generate_password_hash(nueva)
    sb_patch("usuarios", f"id=eq.{user_id}", {"password": nuevo_hash})
    flash("✅ Contraseña actualizada correctamente.", "success")
    return redirect("/ajustes")


# ── Confirmar reset (GET — mostrar página de confirmación) ────────────────────
@bp.route("/confirmar_reset")
@solo_admin
def confirmar_reset():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("confirmar_reset.html")


# ── Reset (POST — eliminar todos los datos) ───────────────────────────────────
@bp.route("/reset", methods=["POST"])
@solo_admin
def reset():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    # Backup automático antes de destruir
    try:
        hacer_backup(owner_id, etiqueta="Antes del reinicio completo")
    except Exception as e:
        flash(f"❌ Error al hacer backup previo: {e}", "error")
        return redirect("/ajustes")

    # Eliminar en orden correcto para respetar foreign keys
    # (hijos antes que padres)
    for tabla in [
        "reproduccion", "pesajes", "sanitario", "produccion",
        "bajas", "ventas", "gastos", "animales", "insumos",
        "alertas", "lotes",
    ]:
        sb_delete(tabla, f"usuario_id=eq.{owner_id}")

    flash("🗑 Todos los datos fueron eliminados. Se creó un respaldo previo.", "success")
    return redirect("/")


# ── Ver backups ────────────────────────────────────────────────────────────────
@bp.route("/backups")
@solo_admin
def ver_backups():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    premium     = es_premium_owner(session["user_id"])
    todos       = sb_get("respaldo", f"usuario_id=eq.{owner_id}&order=fecha.desc")
    total       = len(todos)

    # Plan gratuito: solo los 3 más recientes
    backups = todos if premium else todos[:3]

    return render_template("backups.html",
                           backups    = backups,
                           es_premium = premium,
                           total      = total)


# ── Crear backup manual ────────────────────────────────────────────────────────
@bp.route("/crear_backup", methods=["POST"])
@solo_admin
def crear_backup():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    etiqueta    = request.form.get("etiqueta", "").strip() or "Manual"

    try:
        hacer_backup(owner_id, etiqueta=etiqueta)
        flash(f"✅ Backup '{etiqueta}' creado correctamente.", "success")
    except Exception as e:
        flash(f"❌ Error al crear backup: {e}", "error")

    return redirect("/backups")


# ── Eliminar backup ────────────────────────────────────────────────────────────
@bp.route("/eliminar_backup/<backup_id>", methods=["POST"])
@solo_admin
def eliminar_backup(backup_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    sb_delete("respaldo", f"id=eq.{backup_id}&usuario_id=eq.{owner_id}")
    flash("🗑 Backup eliminado.", "success")
    return redirect("/backups")


# ── Restaurar backup ───────────────────────────────────────────────────────────
@bp.route("/restaurar/<backup_id>")
@solo_admin
def restaurar(backup_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    backup_data = sb_get("respaldo", f"id=eq.{backup_id}&usuario_id=eq.{owner_id}")
    if not backup_data:
        flash("Backup no encontrado.", "error")
        return redirect("/backups")

    datos = backup_data[0].get("datos", {})

    # Backup de seguridad antes de restaurar
    try:
        hacer_backup(owner_id, etiqueta="Antes de restaurar")
    except Exception:
        pass

    # Eliminar datos actuales (mismo orden que reset)
    for tabla in [
        "reproduccion", "pesajes", "sanitario", "produccion",
        "bajas", "ventas", "gastos", "animales", "insumos",
        "alertas", "lotes",
    ]:
        sb_delete(tabla, f"usuario_id=eq.{owner_id}")

    # Restaurar cada tabla del backup (si existe en el JSON)
    tablas_ok   = 0
    tablas_err  = []
    for tabla in TABLAS_DATOS:
        registros = datos.get(tabla, [])
        if not registros:
            continue
        for r in registros:
            r["usuario_id"] = owner_id  # garantizar que el owner es correcto
            r.pop("id", None)           # dejar que Supabase asigne nuevo ID
            try:
                sb_post(tabla, r)
                tablas_ok += 1
            except Exception:
                tablas_err.append(tabla)

    if tablas_err:
        flash(f"⚠️ Restaurado parcialmente. Errores en: {', '.join(set(tablas_err))}", "error")
    else:
        flash(f"✅ Backup restaurado correctamente ({tablas_ok} registros).", "success")

    return redirect("/")