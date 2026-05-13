# routes/proveedores.py
"""
Registro de Proveedores — ERP Pecuario
CRUD de proveedores de insumos, medicamentos y animales.
"""
from flask import Blueprint, render_template, redirect, session, request, flash
from config import sb_get, sb_post, sb_patch, sb_delete
from backup_utils import backup_automatico
from routes.permisos import get_granja_info, solo_admin, es_premium_owner

bp = Blueprint("proveedores", __name__)

CATEGORIAS = {
    "alimento":      "🌽 Alimento",
    "medicamento":   "💊 Medicamento",
    "vacuna":        "💉 Vacuna",
    "equipo":        "🔧 Equipo",
    "animales":      "🐄 Animales",
    "desinfectante": "🧴 Desinfectante",
    "general":       "📦 General",
}


# ── Lista ─────────────────────────────────────────────────────────────────────
@bp.route("/proveedores")
def proveedores():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    if not es_premium_owner(session["user_id"]):
       return render_template("premium_requerido.html", funcion="Registro de Proveedores")
    filtro_cat = request.args.get("categoria", "")

    q = f"usuario_id=eq.{owner_id}&activo=eq.true&order=nombre.asc"
    if filtro_cat:
        q += f"&categoria=eq.{filtro_cat}"

    lista = sb_get("proveedores", q)

    return render_template(
        "proveedores.html",
        proveedores = lista,
        categorias  = CATEGORIAS,
        filtro_cat  = filtro_cat,
        mi_rol      = mi_rol,
    )


# ── Crear ─────────────────────────────────────────────────────────────────────
@bp.route("/crear_proveedor", methods=["POST"])
def crear_proveedor():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])

    nombre    = request.form.get("nombre",    "").strip()
    contacto  = request.form.get("contacto",  "").strip() or None
    telefono  = request.form.get("telefono",  "").strip() or None
    email     = request.form.get("email",     "").strip() or None
    categoria = request.form.get("categoria", "general").strip()
    notas     = request.form.get("notas",     "").strip() or None

    if not nombre:
        flash("El nombre del proveedor es obligatorio.", "error")
        return redirect("/proveedores")

    backup_automatico(owner_id)
    sb_post("proveedores", {
        "usuario_id": owner_id,
        "nombre":     nombre,
        "contacto":   contacto,
        "telefono":   telefono,
        "email":      email,
        "categoria":  categoria,
        "notas":      notas,
        "activo":     True,
    })
    flash(f"✅ Proveedor '{nombre}' registrado.", "success")
    return redirect("/proveedores")


# ── Editar (GET + POST) ───────────────────────────────────────────────────────
@bp.route("/editar_proveedor/<int:prov_id>", methods=["GET", "POST"])
@solo_admin
def editar_proveedor(prov_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    prov = sb_get("proveedores", f"id=eq.{prov_id}&usuario_id=eq.{owner_id}")
    if not prov:
        flash("Proveedor no encontrado.", "error")
        return redirect("/proveedores")

    if request.method == "GET":
        return render_template(
            "editar_proveedor.html",
            prov       = prov[0],
            categorias = CATEGORIAS,
            mi_rol     = mi_rol,
        )

    nombre    = request.form.get("nombre",    "").strip()
    contacto  = request.form.get("contacto",  "").strip() or None
    telefono  = request.form.get("telefono",  "").strip() or None
    email     = request.form.get("email",     "").strip() or None
    categoria = request.form.get("categoria", "general").strip()
    notas     = request.form.get("notas",     "").strip() or None

    if not nombre:
        flash("El nombre es obligatorio.", "error")
        return redirect(f"/editar_proveedor/{prov_id}")

    backup_automatico(owner_id)
    sb_patch("proveedores", f"id=eq.{prov_id}&usuario_id=eq.{owner_id}", {
        "nombre":    nombre,
        "contacto":  contacto,
        "telefono":  telefono,
        "email":     email,
        "categoria": categoria,
        "notas":     notas,
    })
    flash(f"✅ Proveedor '{nombre}' actualizado.", "success")
    return redirect("/proveedores")


# ── Eliminar (soft delete) ────────────────────────────────────────────────────
@bp.route("/eliminar_proveedor/<int:prov_id>", methods=["POST"])
@solo_admin
def eliminar_proveedor(prov_id):
    if "user_id" not in session:
        return redirect("/login")

    owner_id, _ = get_granja_info(session["user_id"])
    prov = sb_get("proveedores", f"id=eq.{prov_id}&usuario_id=eq.{owner_id}")
    if not prov:
        flash("Proveedor no encontrado.", "error")
        return redirect("/proveedores")

    backup_automatico(owner_id)
    sb_patch("proveedores", f"id=eq.{prov_id}&usuario_id=eq.{owner_id}", {"activo": False})
    flash("🗑 Proveedor eliminado.", "success")
    return redirect("/proveedores")