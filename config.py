import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()


def enc(valor):
    """
    Percent-encodea un valor NO confiable (de la URL, query string o formulario)
    antes de interpolarlo dentro de un filtro PostgREST.

    Evita que caracteres como & = ( ) , * escapen del valor y añadan condiciones
    a la consulta (inyección de filtros PostgREST). Con RLS desactivado en
    Supabase, esto es crítico: un filtro manipulado podría saltarse el
    `usuario_id=eq.{owner_id}` y tocar datos de otras granjas.

    Uso:
        sb_get("animales", f"usuario_id=eq.{owner_id}&lote_id=eq.{enc(filtro_lote)}")
    """
    return quote(str(valor), safe="")

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

# ── Sesión HTTP con pool de conexiones + reintentos ───────────────────────────
# Reutiliza conexiones keep-alive (clave para soportar muchos usuarios a la vez)
# en lugar de abrir un socket nuevo en cada llamada. Los reintentos automáticos
# se limitan a GET (idempotente) para no duplicar escrituras en POST/PATCH/DELETE.
_retry = Retry(
    total=3,
    connect=3,
    read=2,
    backoff_factor=0.4,                       # espera 0.4s, 0.8s, 1.6s entre reintentos
    status_forcelist=(502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=_retry)

_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount("https://", _adapter)
_session.mount("http://",  _adapter)


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
        res = _session.get(url, timeout=TIMEOUT)
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
    h = {"Prefer": "return=representation"} if prefer_representation else None
    try:
        res = _session.post(
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


def sb_rpc(funcion, params):
    """
    Llama a una función RPC de PostgREST (/rest/v1/rpc/<funcion>) de forma atómica.
    Útil para evitar condiciones de carrera (p. ej. descontar stock).
    Devuelve el objeto Response (o _FakeErrorResponse si falla la conexión).
    """
    return sb_post(f"rpc/{funcion}", params)


def sb_patch(tabla, filtros, data):
    try:
        return _session.patch(
            f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}",
            json=data,
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
        return _session.delete(
            f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}",
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