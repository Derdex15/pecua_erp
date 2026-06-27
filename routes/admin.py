# routes/admin.py
"""
Panel de administración — ERP Pecuario
Acceso separado del sistema de usuarios normales.

Variables de entorno necesarias en Render:
  ADMIN_USER     → nombre de usuario admin
  ADMIN_PASSWORD → contraseña admin
"""
import os
import hmac
import time
import threading
import datetime
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, enc

bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_USER     = os.getenv("ADMIN_USER", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# ── Rate limiting del login admin (por IP, en memoria por worker) ──────────────
_rl_store: dict[str, list[float]] = {}
_rl_lock  = threading.Lock()

def _rate_limit_ok(ip: str, max_intentos: int = 6, ventana_seg: int = 300) -> bool:
    ahora = time.time()
    with _rl_lock:
        intentos = [t for t in _rl_store.get(ip, []) if ahora - t < ventana_seg]
        if len(intentos) >= max_intentos:
            _rl_store[ip] = intentos
            return False
        intentos.append(ahora)
        _rl_store[ip] = intentos
        return True

def _get_ip() -> str:
    return (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()

PLANES = {
    "1":  {"label": "1 mes",    "precio_usd": 5.00},
    "3":  {"label": "3 meses",  "precio_usd": 13.50},
    "6":  {"label": "6 meses",  "precio_usd": 24.00},
    "12": {"label": "12 meses", "precio_usd": 42.00},
}


# ── Guard admin ───────────────────────────────────────────────────────────────

def _admin_requerido():
    """Retorna True si el admin está logueado, False si no."""
    return session.get("admin_logged_in") is True


# ── Login / Logout ────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if _admin_requerido():
        return redirect("/admin/")

    error = None
    if request.method == "POST":
        ip = _get_ip()

        if not _rate_limit_ok(ip):
            error = "Demasiados intentos. Espera 5 minutos antes de volver a intentarlo."
        elif not ADMIN_USER or not ADMIN_PASSWORD:
            # Sin credenciales configuradas no se permite el acceso (evita login con campos vacíos)
            error = "Acceso administrativo no configurado."
        else:
            usuario    = request.form.get("usuario",    "").strip()
            contrasena = request.form.get("contrasena", "")

            # Comparación en tiempo constante para no filtrar info por timing
            user_ok = hmac.compare_digest(usuario.encode("utf-8"),    ADMIN_USER.encode("utf-8"))
            pass_ok = hmac.compare_digest(contrasena.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))

            if user_ok and pass_ok:
                session["admin_logged_in"] = True
                with _rl_lock:
                    _rl_store.pop(ip, None)
                return redirect("/admin/")
            else:
                error = "Credenciales incorrectas."

    return render_template("admin_login.html", error=error)


@bp.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin/login")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@bp.route("/")
def dashboard():
    if not _admin_requerido():
        return redirect("/admin/login")

    hoy    = str(datetime.date.today())
    buscar = request.args.get("q", "").strip()

    # Usuarios
    if buscar:
        usuarios = sb_get("usuarios", f"username=ilike.*{enc(buscar)}*&order=id.desc&limit=30")
    else:
        usuarios = sb_get("usuarios", "order=id.desc&limit=50")

    # Enriquecer con estado premium
    for u in usuarios:
        sus = sb_get("suscripciones",
                     f"usuario_id=eq.{u['id']}"
                     f"&plan=eq.premium&activa=eq.true&fecha_fin=gte.{hoy}")
        u["es_premium"]  = bool(sus)
        u["fecha_fin"]   = sus[0]["fecha_fin"] if sus else None
        u["tiene_trial"] = False
        if sus and sus[0].get("metodo_pago") == "trial":
            u["tiene_trial"] = True

    # Últimos pagos registrados
    pagos = sb_get("pagos", "order=fecha.desc&limit=20")

    # Stats rápidas
    total_usuarios = len(sb_get("usuarios", "select=id"))
    total_premium  = len(sb_get("suscripciones",
                                f"plan=eq.premium&activa=eq.true&fecha_fin=gte.{hoy}"))

    return render_template(
        "admin_panel.html",
        usuarios        = usuarios,
        pagos           = pagos,
        buscar          = buscar,
        total_usuarios  = total_usuarios,
        total_premium   = total_premium,
        planes          = PLANES,
    )


# ── Activar premium manualmente ───────────────────────────────────────────────

@bp.route("/activar", methods=["POST"])
def activar():
    if not _admin_requerido():
        return redirect("/admin/login")

    user_id  = request.form.get("user_id",  "").strip()
    meses    = request.form.get("meses",    "1").strip()
    monto    = request.form.get("monto",    "0").strip()
    metodo   = request.form.get("metodo",   "transferencia").strip()
    notas    = request.form.get("notas",    "").strip()

    if not user_id or not user_id.replace("-", "").isalnum() or meses not in PLANES:
        flash("Datos inválidos.", "error")
        return redirect("/admin/")

    try:
        meses_int = int(meses)
        monto_f   = float(monto) if monto else 0.0
    except ValueError:
        flash("Meses o monto inválido.", "error")
        return redirect("/admin/")

    hoy         = datetime.date.today()
    existente   = sb_get("suscripciones", f"usuario_id=eq.{user_id}")

    if existente:
        fecha_actual = existente[0].get("fecha_fin")
        base = (datetime.date.fromisoformat(fecha_actual)
                if fecha_actual and fecha_actual > str(hoy) else hoy)
        nueva_fecha = base + datetime.timedelta(days=30 * meses_int)
        sb_patch("suscripciones", f"usuario_id=eq.{user_id}", {
            "plan":         "premium",
            "activa":       True,
            "fecha_inicio": str(hoy),
            "fecha_fin":    str(nueva_fecha),
            "metodo_pago":  metodo,
        })
    else:
        nueva_fecha = hoy + datetime.timedelta(days=30 * meses_int)
        sb_post("suscripciones", {
            "usuario_id":   user_id,
            "plan":         "premium",
            "activa":       True,
            "fecha_inicio": str(hoy),
            "fecha_fin":    str(nueva_fecha),
            "metodo_pago":  metodo,
        })

    # Registrar pago manual
    sb_post("pagos", {
        "usuario_id":      user_id,
        "monto":           monto_f,
        "meses":           meses_int,
        "estado":          "completado",
        "metodo":          metodo,
        "referencia_pago": notas or f"Activación manual — {metodo}",
    })

    usuario = sb_get("usuarios", f"id=eq.{user_id}")
    nombre  = usuario[0]["username"] if usuario else user_id
    plan    = PLANES[meses]["label"]

    flash(f"✅ Premium activado para {nombre} — {plan} hasta {nueva_fecha.strftime('%d/%m/%Y')}.",
          "success")
    return redirect("/admin/")


# ── Desactivar premium ────────────────────────────────────────────────────────

@bp.route("/desactivar", methods=["POST"])
def desactivar():
    if not _admin_requerido():
        return redirect("/admin/login")

    user_id = request.form.get("user_id", "").strip()
    if not user_id or not user_id.replace("-", "").isalnum():
        flash("Usuario inválido.", "error")
        return redirect("/admin/")

    sb_patch("suscripciones", f"usuario_id=eq.{user_id}",
             {"activa": False})

    usuario = sb_get("usuarios", f"id=eq.{user_id}")
    nombre  = usuario[0]["username"] if usuario else user_id
    flash(f"⚠️ Premium desactivado para {nombre}.", "info")
    return redirect("/admin/")