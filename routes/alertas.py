# routes/alertas.py
"""
Centro de alertas — ERP Pecuario
Ruta que faltaba: el badge del navbar lleva aquí.
"""
from flask import Blueprint, render_template, redirect, session, request, flash, jsonify
from config import sb_get, sb_patch, sb_delete
from routes.permisos import get_granja_info

bp = Blueprint("alertas", __name__)


@bp.route("/alertas")
def alertas():
    if "user_id" not in session:
        return redirect("/login")

    owner_id, mi_rol = get_granja_info(session["user_id"])
    mostrar          = request.args.get("mostrar", "no_leidas")

    q = f"usuario_id=eq.{owner_id}&order=fecha_alerta.desc"
    if mostrar == "no_leidas":
        q += "&leida=eq.false"

    todas = sb_get("alertas", q)

    lotes_idx = {l["id"]: l["nombre"]
                 for l in sb_get("lotes", f"usuario_id=eq.{owner_id}")}
    for a in todas:
        a["lote_nombre"] = lotes_idx.get(a.get("lote_id"), "")

    total_no_leidas = len(sb_get("alertas",
                                 f"usuario_id=eq.{owner_id}&leida=eq.false"))

    return render_template("alertas.html",
                           alertas          = todas,
                           mostrar          = mostrar,
                           total_no_leidas  = total_no_leidas,
                           mi_rol           = mi_rol)


@bp.route("/alertas/marcar_leida/<alerta_id>", methods=["POST"])
def marcar_leida(alerta_id):
    if "user_id" not in session:
        return jsonify({"ok": False}), 401
    owner_id, _ = get_granja_info(session["user_id"])
    sb_patch("alertas", f"id=eq.{alerta_id}&usuario_id=eq.{owner_id}", {"leida": True})
    return jsonify({"ok": True})


@bp.route("/alertas/marcar_todas_leidas", methods=["POST"])
def marcar_todas_leidas():
    if "user_id" not in session:
        return redirect("/login")
    owner_id, _ = get_granja_info(session["user_id"])
    sb_patch("alertas", f"usuario_id=eq.{owner_id}&leida=eq.false", {"leida": True})
    flash("✅ Todas las alertas marcadas como leídas.", "success")
    return redirect("/alertas")


@bp.route("/alertas/eliminar/<alerta_id>", methods=["POST"])
def eliminar_alerta(alerta_id):
    if "user_id" not in session:
        return jsonify({"ok": False}), 401
    owner_id, _ = get_granja_info(session["user_id"])
    sb_delete("alertas", f"id=eq.{alerta_id}&usuario_id=eq.{owner_id}")
    return jsonify({"ok": True})