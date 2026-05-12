import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL:
    raise ValueError("❌ SUPABASE_URL no configurada en .env")
if not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_KEY no configurada en .env")

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

TIMEOUT = (5, 10)


def _safe_json(res):
    try:
        data = res.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


class _FakeErrorResponse:
    """Respuesta simulada para cuando falla la conexión, evita excepciones en los blueprints."""
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.text = f"Error simulado {status_code}"

    def json(self):
        return []

    @property
    def ok(self):
        return False


def sb_get(tabla, filtros=""):
    url = f"{SUPABASE_URL}/rest/v1/{tabla}"
    if filtros:
        url += f"?{filtros}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        return _safe_json(res)
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
        return _safe_json(res) if prefer_representation else res
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en POST {tabla}")
        return [] if prefer_representation else _FakeErrorResponse(504)
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en POST {tabla}")
        return [] if prefer_representation else _FakeErrorResponse(503)
    except Exception as e:
        print(f"❌ Error inesperado en POST {tabla}: {e}")
        return [] if prefer_representation else _FakeErrorResponse(500)


def sb_patch(tabla, filtros, data):
    try:
        return requests.patch(
            f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}",
            json=data,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en PATCH {tabla}")
        return _FakeErrorResponse(504)
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en PATCH {tabla}")
        return _FakeErrorResponse(503)
    except Exception as e:
        print(f"❌ Error inesperado en PATCH {tabla}: {e}")
        return _FakeErrorResponse(500)


def sb_delete(tabla, filtros):
    try:
        return requests.delete(
            f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.exceptions.Timeout:
        print(f"⏱ TIMEOUT en DELETE {tabla}")
        return _FakeErrorResponse(504)
    except requests.exceptions.ConnectionError:
        print(f"📡 SIN CONEXIÓN en DELETE {tabla}")
        return _FakeErrorResponse(503)
    except Exception as e:
        print(f"❌ Error inesperado en DELETE {tabla}: {e}")
        return _FakeErrorResponse(500)