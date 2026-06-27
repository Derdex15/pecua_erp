"""
Probador del webhook de Lemon Squeezy — SIN necesidad de una compra real.

Genera un payload simulado con una firma HMAC-SHA256 VÁLIDA (usando tu
LS_WEBHOOK_SECRET) y lo envía a tu endpoint /webhook/lemonsqueezy.
Sirve para verificar que la activación de Premium funciona de punta a punta.

Uso:
    # 1) Exporta el mismo secreto que tienes en Render:
    #    PowerShell:  $env:LS_WEBHOOK_SECRET="tu_secreto"
    #    bash:        export LS_WEBHOOK_SECRET="tu_secreto"
    #
    # 2) Ejecuta apuntando a tu servidor (local o staging) y a un user_id REAL:
    #        python test_ls_webhook.py --url http://127.0.0.1:5000 --user-id 5
    #        python test_ls_webhook.py --url https://erpecuario.com --user-id 5 --event subscription_created
    #
    # 3) Revisa en la app si ese usuario quedó Premium, y la tabla 'pagos'.
    #
    # ⚠️ Úsalo contra un user_id de PRUEBA: escribe en las tablas reales
    #    'suscripciones' y 'pagos'. Para limpiar, desactiva desde /admin.
"""
import os
import sys
import json
import hmac
import hashlib
import argparse
import requests


def construir_payload(event: str, user_id: str) -> dict:
    """Imita la estructura que envía Lemon Squeezy."""
    return {
        "meta": {
            "event_name":  event,
            "custom_data": {"user_id": str(user_id)},
        },
        "data": {
            "id": "test-sub-0001",
            "type": "subscriptions",
            "attributes": {
                "status":       "active",
                "user_email":   "prueba@example.com",
                "variant_name": "Premium mensual",
            },
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url",     default="http://127.0.0.1:5000",
                   help="Base URL del servidor (sin /webhook/...)")
    p.add_argument("--user-id", required=True, help="user_id a activar (de prueba)")
    p.add_argument("--event",   default="subscription_payment_success",
                   help="subscription_created | subscription_payment_success | "
                        "subscription_cancelled | subscription_expired")
    args = p.parse_args()

    secret = os.getenv("LS_WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("❌ Falta LS_WEBHOOK_SECRET en el entorno (el mismo que en Render).")

    body = json.dumps(construir_payload(args.event, args.user_id)).encode("utf-8")
    firma = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    endpoint = args.url.rstrip("/") + "/webhook/lemonsqueezy"
    print(f"→ POST {endpoint}")
    print(f"  evento={args.event}  user_id={args.user_id}")

    r = requests.post(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": firma},
        timeout=15,
    )
    print(f"← {r.status_code}: {r.text[:200]}")

    if r.status_code == 200:
        print("✅ El webhook aceptó el evento (firma válida y procesado).")
    elif r.status_code == 403:
        print("⚠️ Firma rechazada: el secreto no coincide con el del servidor.")
    elif r.status_code == 503:
        print("⚠️ El servidor no tiene LS_WEBHOOK_SECRET configurado.")
    else:
        print("⚠️ Respuesta inesperada — revisa los logs del servidor.")

    # Prueba negativa: firma inválida debe dar 403
    print("\n→ Prueba de seguridad: firma inválida debe ser rechazada…")
    r2 = requests.post(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": "firma_falsa"},
        timeout=15,
    )
    print(f"← {r2.status_code}: {r2.text[:120]}")
    print("✅ Correcto: rechazó la firma falsa." if r2.status_code == 403
          else "❌ ATENCIÓN: aceptó una firma inválida — revisa la verificación.")


if __name__ == "__main__":
    main()
