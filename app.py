"""
ERP Pecuario — Punto de entrada principal
Flask + Supabase + Firebase FCM
"""
import os
import json
from datetime import timedelta
from flask import Flask, render_template, send_from_directory
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__)

    app.secret_key = os.getenv("SECRET_KEY")
    if not app.secret_key:
        raise ValueError("❌ SECRET_KEY no configurada en .env")

    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["SESSION_COOKIE_HTTPONLY"]    = True

    if os.getenv("ENV") == "production":
        app.config["SESSION_COOKIE_SECURE"]   = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    else:
        app.config["SESSION_COOKIE_SECURE"]   = False
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # ── Blueprints ──────────────────────────────────────────────
    from routes.auth           import bp as auth_bp
    from routes.inventario     import bp as inventario_bp
    from routes.ventas         import bp as ventas_bp
    from routes.gastos         import bp as gastos_bp
    from routes.reportes       import bp as reportes_bp
    from routes.ajustes        import bp as ajustes_bp
    from routes.sanitario      import bp as sanitario_bp
    from routes.suscripciones  import bp as suscripciones_bp
    from routes.produccion     import bp as produccion_bp
    from routes.granja         import bp as granja_bp
    from routes.bajas          import bp as bajas_bp
    from routes.animales       import bp as animales_bp
    from routes.reproduccion   import bp as reproduccion_bp
    from routes.pesajes        import bp as pesajes_bp
    from routes.onboarding     import bp as onboarding_bp
    from routes.notificaciones import bp as notificaciones_bp
    from routes.insumos        import bp as insumos_bp        # ← NUEVO

    for blueprint in [
        auth_bp, inventario_bp, ventas_bp, gastos_bp,
        reportes_bp, ajustes_bp, sanitario_bp, suscripciones_bp,
        produccion_bp, granja_bp, bajas_bp, animales_bp,
        reproduccion_bp, pesajes_bp, onboarding_bp,
        notificaciones_bp, insumos_bp,
    ]:
        app.register_blueprint(blueprint)

    # ── PWA ─────────────────────────────────────────────────────
    @app.route("/sw.js")
    def service_worker():
        r = send_from_directory(
            os.path.join(app.root_path, "static"), "sw.js",
            mimetype="application/javascript")
        r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return r

    @app.route("/firebase-messaging-sw.js")
    def firebase_messaging_sw():
        r = send_from_directory(
            os.path.join(app.root_path, "static"),
            "firebase-messaging-sw.js",
            mimetype="application/javascript")
        r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return r

    @app.route("/manifest.json")
    def manifest():
        return send_from_directory(
            os.path.join(app.root_path, "static"), "manifest.json",
            mimetype="application/manifest+json")

    # ── TWA ──────────────────────────────────────────────────────
    @app.route("/.well-known/assetlinks.json")
    def assetlinks():
        links = [{"relation": ["delegate_permission/common.handle_all_urls"],
                  "target": {
                      "namespace": "android_app",
                      "package_name": os.getenv("TWA_PACKAGE_NAME", "com.erpecuario.app"),
                      "sha256_cert_fingerprints": [
                          os.getenv("TWA_SHA256_CERT", "REEMPLAZAR")],
                  }}]
        r = app.response_class(
            response=json.dumps(links), status=200, mimetype="application/json")
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.route("/privacidad")
    def privacidad():
        return render_template("privacidad.html")

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("500.html"), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)