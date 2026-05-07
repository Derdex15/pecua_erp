import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = "https://llvfjcancffgkdwwigfp.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("❌ No se cargó SUPABASE_KEY desde .env")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# Timeout global para todas las llamadas a Supabase.
# - connect: tiempo máximo para establecer conexión (segundos)
# - read:    tiempo máximo esperando respuesta del servidor
TIMEOUT = (5, 10)


def safe_json(res):
    """Devuelve lista segura desde respuesta de Supabase."""
    try:
        data = res.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def sb_get(tabla, filtros=""):
    """
    GET a Supabase con filtros opcionales.
    Retorna [] si hay error de red o timeout — nunca lanza excepción.
    """
    url = f"{SUPABASE_URL}/rest/v1/{tabla}"
    if filtros:
        url += f"?{filtros}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        return safe_json(res)
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en GET {tabla}")
        return []
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en GET {tabla}")
        return []
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP {e.response.status_code} en GET {tabla}: {e.response.text[:200]}")
        return []
    except Exception as e:
        print(f"❌ Error inesperado en GET {tabla}: {e}")
        return []


def sb_post(tabla, data, prefer_representation=False):
    """
    POST a Supabase.
    Retorna lista si prefer_representation=True, Response si no.
    Retorna [] / Response con status 500 si falla.
    """
    h = {**HEADERS}
    if prefer_representation:
        h["Prefer"] = "return=representation"
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/{tabla}",
            json=data,
            headers=h,
            timeout=TIMEOUT,
        )
        return safe_json(res) if prefer_representation else res
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en POST {tabla}")
        return [] if prefer_representation else _fake_error_response(504)
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en POST {tabla}")
        return [] if prefer_representation else _fake_error_response(503)
    except Exception as e:
        print(f"❌ Error inesperado en POST {tabla}: {e}")
        return [] if prefer_representation else _fake_error_response(500)


def sb_patch(tabla, filtros, data):
    """
    PATCH a Supabase.
    Retorna Response (real o simulada con error) — nunca lanza excepción.
    """
    try:
        return requests.patch(
            f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}",
            json=data,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en PATCH {tabla}")
        return _fake_error_response(504)
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en PATCH {tabla}")
        return _fake_error_response(503)
    except Exception as e:
        print(f"❌ Error inesperado en PATCH {tabla}: {e}")
        return _fake_error_response(500)


def sb_delete(tabla, filtros):
    """
    DELETE a Supabase.
    Retorna Response (real o simulada con error) — nunca lanza excepción.
    """
    try:
        return requests.delete(
            f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en DELETE {tabla}")
        return _fake_error_response(504)
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en DELETE {tabla}")
        return _fake_error_response(503)
    except Exception as e:
        print(f"❌ Error inesperado en DELETE {tabla}: {e}")
        return _fake_error_response(500)


# ── Helpers internos ──────────────────────────────────────────────────────────

class _fake_error_response:
    """Objeto que imita requests.Response con status_code de error."""
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.text = f"Error simulado {status_code}"

    def json(self):
        return []

    @property
    def ok(self):
        return False