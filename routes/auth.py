# routes/auth.py
import re
from flask import Blueprint, render_template, redirect, session, request, flash
from werkzeug.security import check_password_hash, generate_password_hash
from config import sb_get, sb_post

bp = Blueprint("auth", __name__)


def _username_valido(username: str) -> bool:
    return bool(re.match(r"^[\w\-]{3,30}$", username))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect("/")

    error = None
    if request.method == "POST":
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
                flash(f"👋 Bienvenido, {username}.", "success")
                return redirect("/")
            else:
                error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error)


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if "user_id" in session:
        return redirect("/")

    error = None
    if request.method == "POST":
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
                    # ← NUEVO: redirigir al onboarding en lugar del dashboard
                    return redirect("/onboarding")
                else:
                    error = "Error al crear la cuenta. Intenta de nuevo."

    return render_template("registro.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")