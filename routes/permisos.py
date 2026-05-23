# routes/permisos.py
"""
Control de acceso por rol para ERP Pecuario.

Exporta:
  - login_required              → decorador que redirige a /login si no hay sesión
  - get_granja_info(user_id)    → (owner_id, rol)
  - solo_admin                  → decorador que bloquea operadores
  - es_premium_owner(user_id)   → bool (verifica premium del dueño de la granja)

Uso en cualquier blueprint:
    from routes.permisos import get_granja_info, login_required, solo_admin, es_premium_owner
"""

import datetime
from functools import wraps
from flask import session, redirect, flash
from config import sb_get


# ── login_required ────────────────────────────────────────────────────────────

def login_required(f):
    """
    Decorador que redirige a /login si el usuario no está autenticado.
    Úsalo en TODAS las rutas que requieran sesión activa.

    Ejemplo:
        @bp.route("/mi_ruta")
        @login_required
        def mi_ruta():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


# ── Consulta principal ────────────────────────────────────────────────────────

def get_granja_info(user_id):
    """
    Retorna (owner_id, rol) para el user_id dado.

    Casos:
      · Es dueño de una granja  → (user_id, "admin")
      · Es miembro activo       → (owner_id_del_dueño, rol_asignado)
      · Sin granja propia       → (user_id, "admin")  ← acceso total a sus datos
    """
    # ¿Es dueño de alguna granja?
    granja = sb_get("granjas", f"owner_id=eq.{user_id}")
    if granja:
        return user_id, "admin"

    # ¿Es miembro activo de alguna granja?
    membresia = sb_get("granja_miembros",
                       f"usuario_id=eq.{user_id}&activo=eq.true")
    if membresia:
        granja_id = membresia[0].get("granja_id")
        granja    = sb_get("granjas", f"id=eq.{granja_id}")
        if granja:
            rol = membresia[0].get("rol", "operador")
            return granja[0]["owner_id"], rol

    # Sin granja: sus propios datos, rol admin
    return user_id, "admin"


# ── Verificación de premium (del dueño de la granja) ─────────────────────────

def es_premium_owner(user_id):
    """
    Verifica si el dueño de la granja del user_id tiene suscripción premium activa.
    Si el usuario es independiente (sin granja), verifica su propio premium.
    """
    owner_id, _ = get_granja_info(user_id)
    hoy = str(datetime.date.today())
    res = sb_get("suscripciones",
                 f"usuario_id=eq.{owner_id}"
                 f"&plan=eq.premium&activa=eq.true&fecha_fin=gte.{hoy}")
    return bool(res)


# ── Decorador solo_admin ──────────────────────────────────────────────────────

def solo_admin(f):
    """
    Decorador que bloquea el acceso a cualquier usuario con rol 'operador'.
    Requiere que login_required ya haya validado la sesión.
    Colócalo inmediatamente debajo de @bp.route(...).

    Ejemplo:
        @bp.route("/eliminar_lote/<lote_id>", methods=["POST"])
        @login_required
        @solo_admin
        def eliminar_lote(lote_id):
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        _, rol = get_granja_info(session["user_id"])
        if rol != "admin":
            flash("⛔ Solo el administrador puede realizar esta acción.", "error")
            return redirect("/")
        return f(*args, **kwargs)
    return decorated