# routes/recuperar_password.py
"""
Recuperación de contraseña por email — ERP Pecuario

Variables de entorno necesarias en Render:
  SMTP_HOST      → smtp.gmail.com  (o el de tu proveedor)
  SMTP_PORT      → 587
  SMTP_USER      → tu-correo@gmail.com
  SMTP_PASSWORD  → contraseña de aplicación de Gmail (no tu contraseña normal)
  FROM_EMAIL     → soporte@erpecuario.com  (o el mismo SMTP_USER)
  APP_URL        → https://erpecuario.com

Para Gmail: activa "Contraseñas de aplicación" en tu cuenta Google
(Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones)
"""
import os
import secrets
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, render_template, redirect, request, flash
from werkzeug.security import generate_password_hash
from config import sb_get, sb_post, sb_patch, sb_delete

bp = Blueprint("recuperar_password", __name__)

APP_URL       = os.getenv("APP_URL", "https://erpecuario.com")
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL    = os.getenv("FROM_EMAIL", SMTP_USER)
TOKEN_EXPIRY_MINUTOS = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def _enviar_email(destinatario: str, asunto: str, cuerpo_html: str) -> bool:
    """Envía un email. Retorna True si tuvo éxito, False si falló."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("[EMAIL] SMTP no configurado — revisa SMTP_USER y SMTP_PASSWORD en Render")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"]    = f"ERP Pecuario <{FROM_EMAIL}>"
        msg["To"]      = destinatario
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(FROM_EMAIL, [destinatario], msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL] Error al enviar: {e}")
        return False


def _limpiar_tokens_vencidos(user_id):
    """Elimina tokens expirados del usuario para mantener la tabla limpia."""
    ahora = datetime.datetime.utcnow().isoformat()
    try:
        sb_delete("password_reset_tokens",
                  f"usuario_id=eq.{user_id}&expires_at=lt.{ahora}")
    except Exception:
        pass


# ── Paso 1: formulario para pedir el email ────────────────────────────────────

@bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "GET":
        return render_template("recuperar.html")

    email = request.form.get("email", "").strip().lower()

    if not email or "@" not in email:
        flash("Ingresa un correo electrónico válido.", "error")
        return render_template("recuperar.html")

    # Buscar usuario con ese email
    usuarios = sb_get("usuarios", f"email=eq.{email}")

    # Por seguridad: siempre mostrar el mismo mensaje aunque no exista el email
    # (evitar enumerar usuarios)
    if usuarios:
        user_id = usuarios[0]["id"]
        _limpiar_tokens_vencidos(user_id)

        token    = secrets.token_urlsafe(32)
        expires  = (datetime.datetime.utcnow() +
                    datetime.timedelta(minutes=TOKEN_EXPIRY_MINUTOS)).isoformat()

        sb_post("password_reset_tokens", {
            "usuario_id": user_id,
            "token":      token,
            "expires_at": expires,
        })

        link = f"{APP_URL}/reset_password/{token}"
        cuerpo = f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
          <h2 style="color:#27ae60;">🐄 ERP Pecuario</h2>
          <h3>Recuperación de contraseña</h3>
          <p>Recibimos una solicitud para restablecer la contraseña de tu cuenta.</p>
          <p>Haz clic en el botón para crear una nueva contraseña:</p>
          <div style="text-align:center;margin:30px 0;">
            <a href="{link}"
               style="background:#27ae60;color:white;padding:14px 28px;
                      border-radius:8px;text-decoration:none;font-size:16px;
                      font-weight:bold;display:inline-block;">
              Restablecer contraseña
            </a>
          </div>
          <p style="color:#999;font-size:13px;">
            Este enlace expira en {TOKEN_EXPIRY_MINUTOS} minutos.<br>
            Si no solicitaste este cambio, ignora este correo.
          </p>
          <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
          <p style="color:#bbb;font-size:12px;">ERP Pecuario · soporte@erpecuario.com</p>
        </div>
        """
        _enviar_email(email, "Recupera tu contraseña — ERP Pecuario", cuerpo)

    flash("Si ese correo está registrado, recibirás un enlace en los próximos minutos. "
          "Revisa también tu carpeta de spam.", "info")
    return render_template("recuperar.html", enviado=True)


# ── Paso 2: formulario para ingresar la nueva contraseña ──────────────────────

@bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    # Validar token
    ahora    = datetime.datetime.utcnow().isoformat()
    registros = sb_get("password_reset_tokens",
                        f"token=eq.{token}&expires_at=gte.{ahora}")

    if not registros:
        flash("Este enlace no es válido o ya expiró. Solicita uno nuevo.", "error")
        return redirect("/recuperar")

    user_id = registros[0]["usuario_id"]

    if request.method == "GET":
        return render_template("reset_password.html", token=token)

    nueva    = request.form.get("password",  "").strip()
    confirmar = request.form.get("confirmar", "").strip()

    if not nueva or not confirmar:
        flash("Completa ambos campos.", "error")
        return render_template("reset_password.html", token=token)

    if len(nueva) < 6:
        flash("La contraseña debe tener al menos 6 caracteres.", "error")
        return render_template("reset_password.html", token=token)

    if nueva != confirmar:
        flash("Las contraseñas no coinciden.", "error")
        return render_template("reset_password.html", token=token)

    # Actualizar contraseña
    sb_patch("usuarios", f"id=eq.{user_id}",
             {"password": generate_password_hash(nueva)})

    # Eliminar el token usado (y todos los del usuario)
    sb_delete("password_reset_tokens", f"usuario_id=eq.{user_id}")

    flash("✅ Contraseña actualizada. Ya puedes iniciar sesión.", "success")
    return redirect("/login")