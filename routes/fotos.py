# routes/fotos.py
"""
Fotos por animal o lote — ERP Pecuario

Almacena imágenes en Supabase Storage y registra la URL en la tabla fotos.

PRERREQUISITOS (usuario debe hacer manualmente):
  1. En Supabase → Storage → New bucket
     Nombre: fotos  |  Tipo: Public bucket  ✅
  2. Ejecutar supabase_tablas_nuevas.sql para crear la tabla fotos

Formatos aceptados : JPEG, PNG, WebP
Tamaño máximo      : 5 MB por imagen
"""
import os
import uuid
import datetime
import requests as http
from flask import Blueprint, request, session, jsonify
from config import sb_get, sb_post, sb_delete, SUPABASE_URL, SUPABASE_KEY
from routes.permisos import get_granja_info

bp = Blueprint("fotos", __name__)

BUCKET      = "fotos"
MAX_MB      = 5
MIME_OK     = {"image/jpeg", "image/png", "image/webp"}
EXT_MAP     = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _public_url(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


def _storage_upload(data: bytes, mime: str, path: str) -> str | None:
    """Sube bytes al bucket. Retorna URL pública o None si falla."""
    res = http.post(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  mime,
            "x-upsert":      "true",
        },
        timeout=(10, 60),
    )
    if res.status_code in (200, 201):
        return _public_url(path)
    print(f"❌ Storage {res.status_code}: {res.text[:300]}")
    return None


def _storage_delete(url: str):
    """Elimina un archivo del bucket dado su URL pública."""
    try:
        path = url.split(f"/object/public/{BUCKET}/")[-1]
        http.delete(
            f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
            headers={"Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=(5, 15),
        )
    except Exception as e:
        print(f"⚠️ No se pudo eliminar archivo de Storage: {e}")


# ── Listar fotos de una entidad ───────────────────────────────────────────────
@bp.route("/api/fotos/<entidad_tipo>/<int:entidad_id>")
def listar_fotos(entidad_tipo, entidad_id):
    if "user_id" not in session:
        return jsonify([])
    if entidad_tipo not in ("animal", "lote"):
        return jsonify([])
    owner_id, _ = get_granja_info(session["user_id"])
    fotos = sb_get(
        "fotos",
        f"usuario_id=eq.{owner_id}"
        f"&entidad_tipo=eq.{entidad_tipo}"
        f"&entidad_id=eq.{entidad_id}"
        f"&order=fecha.desc"
    )
    return jsonify(fotos)


# ── Subir foto ────────────────────────────────────────────────────────────────
@bp.route("/api/fotos/subir", methods=["POST"])
def subir_foto():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "no autenticado"}), 401

    owner_id, _ = get_granja_info(session["user_id"])
    if not es_premium_owner(session["user_id"]):
       return render_template("premium_requerido.html", funcion="Calendario de Actividades")

    entidad_tipo = request.form.get("entidad_tipo", "").strip()
    entidad_id   = request.form.get("entidad_id",   "").strip()

    if entidad_tipo not in ("animal", "lote") or not entidad_id:
        return jsonify({"ok": False, "error": "parámetros inválidos"}), 400

    archivo = request.files.get("foto")
    if not archivo:
        return jsonify({"ok": False, "error": "no se recibió archivo"}), 400

    mime = archivo.content_type
    if mime not in MIME_OK:
        return jsonify({"ok": False, "error": "formato no permitido (JPG/PNG/WEBP)"}), 415

    data = archivo.read()
    if len(data) > MAX_MB * 1024 * 1024:
        return jsonify({"ok": False, "error": f"tamaño máximo {MAX_MB} MB"}), 413

    ext  = EXT_MAP[mime]
    path = f"{owner_id}/{entidad_tipo}/{entidad_id}/{uuid.uuid4().hex[:10]}.{ext}"

    url = _storage_upload(data, mime, path)
    if not url:
        return jsonify({"ok": False,
                        "error": "Error al subir. Verifica que el bucket 'fotos' existe y es público."}), 500

    foto = sb_post("fotos", {
        "usuario_id":   owner_id,
        "entidad_tipo": entidad_tipo,
        "entidad_id":   int(entidad_id),
        "url":          url,
        "nombre":       archivo.filename or "",
        "fecha":        datetime.datetime.now().isoformat(),
    }, prefer_representation=True)

    foto_id = foto[0]["id"] if foto else None
    return jsonify({"ok": True, "url": url, "id": foto_id})


# ── Eliminar foto (solo admin) ────────────────────────────────────────────────
@bp.route("/api/fotos/eliminar/<int:foto_id>", methods=["POST"])
def eliminar_foto(foto_id):
    if "user_id" not in session:
        return jsonify({"ok": False}), 401

    owner_id, rol = get_granja_info(session["user_id"])
    if rol != "admin":
        return jsonify({"ok": False, "error": "solo administrador"}), 403

    foto = sb_get("fotos", f"id=eq.{foto_id}&usuario_id=eq.{owner_id}")
    if not foto:
        return jsonify({"ok": False, "error": "foto no encontrada"}), 404

    _storage_delete(foto[0]["url"])
    sb_delete("fotos", f"id=eq.{foto_id}&usuario_id=eq.{owner_id}")
    return jsonify({"ok": True})