# routes/auth.py
import re
import time
import threading
from flask import Blueprint, render_template, redirect, session, request, flash
from werkzeug.security import check_password_hash, generate_password_hash
from config import sb_get, sb_post

bp = Blueprint("auth", __name__)

# ── Rate limiting simple (por IP, en memoria por worker) ──────────────────────
# Con 2 workers en Gunicorn el límite efectivo es 2× por worker.
# Para producción con alta carga: reemplazar por Flask-Limiter + Redis.
_rl_store: dict[str, list[float]] = {}
_rl_lock  = threading.Lock()

def _rate_limit_ok(ip: str, max_intentos: int = 8, ventana_seg: int = 300) -> bool:
    """
    Retorna True si el IP puede intentar login.
    Bloquea si hizo más de `max_intentos` en los últimos `ventana_seg` segundos.
    """
    ahora = time.time()
    with _rl_lock:
        intentos = _rl_store.get(ip, [])
        # Limpiar intentos fuera de la ventana
        intentos = [t for t in intentos if ahora - t < ventana_seg]
        if len(intentos) >= max_intentos:
            _rl_store[ip] = intentos
            return False
        intentos.append(ahora)
        _rl_store[ip] = intentos
        return True

def _get_ip() -> str:
    # Render pone la IP real en X-Forwarded-For
    return (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()


# ── Validación de username ────────────────────────────────────────────────────

def _username_valido(username: str) -> bool:
    return bool(re.match(r"^[\w\-]{3,30}$", username))


# ── Login ─────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect("/")

    error = None
    if request.method == "POST":
        ip = _get_ip()

        if not _rate_limit_ok(ip):
            error = "Demasiados intentos fallidos. Espera 5 minutos antes de volver a intentarlo."
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if not username or not password:
                error = "Completa usuario y contraseña."
            elif not _username_valido(username):
                error = "Usuario inválido. Solo letras, números, - y _."
            else:
                res = sb_get("usuarios", f"username=eq.{username}")
                if res and check_password_hash(res[0]["password"], password):
                    session.permanent   = True
                    session["user_id"]  = res[0]["id"]
                    session["username"] = username
                    # Limpiar contador de intentos al loguearse bien
                    with _rl_lock:
                        _rl_store.pop(ip, None)
                    flash(f"👋 Bienvenido, {username}.", "success")
                    return redirect("/")
                else:
                    error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error)


# ── Registro ──────────────────────────────────────────────────────────────────

@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if "user_id" in session:
        return redirect("/")

    error = None
    if request.method == "POST":
        ip = _get_ip()

        if not _rate_limit_ok(ip, max_intentos=5, ventana_seg=600):
            error = "Demasiados intentos. Espera 10 minutos."
        else:
            username  = request.form.get("username",  "").strip()
            password  = request.form.get("password",  "")
            confirmar = request.form.get("confirmar", "")

            if not username or not password or not confirmar:
                error = "Completa todos los campos."
            elif not _username_valido(username):
                error = "Solo letras, números, guiones y guiones bajos (3-30 caracteres)."
            elif len(password) < 6:
                error = "La contraseña debe tener al menos 6 caracteres."
            elif password != confirmar:
                error = "Las contraseñas no coinciden."
            else:
                if sb_get("usuarios", f"username=eq.{username}"):
                    error = "Ese nombre de usuario ya está en uso."
                else:
                    nuevo = sb_post(
                        "usuarios",
                        {"username": username, "password": generate_password_hash(password)},
                        prefer_representation=True,
                    )
                    if nuevo:
                        session.permanent   = True
                        session["user_id"]  = nuevo[0]["id"]
                        session["username"] = username
                        return redirect("/onboarding")
                    else:
                        error = "Error al crear la cuenta. Intenta de nuevo."

    return render_template("registro.html", error=error)


# ── Logout ────────────────────────────────────────────────────────────────────

@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")