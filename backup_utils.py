import datetime
from config import sb_get, sb_post


def hacer_backup(user_id, etiqueta="", automatico=False):
    """
    Crea un snapshot completo de los datos del usuario en la tabla respaldo.
    Incluye TODAS las tablas que contienen datos propios del usuario/owner.
    """
    print("📦 HACIENDO BACKUP...")

    lotes        = sb_get("lotes",        f"usuario_id=eq.{user_id}")
    ventas       = sb_get("ventas",       f"usuario_id=eq.{user_id}")
    gastos       = sb_get("gastos",       f"usuario_id=eq.{user_id}")
    sanitario    = sb_get("sanitario",    f"usuario_id=eq.{user_id}")
    produccion   = sb_get("produccion",   f"usuario_id=eq.{user_id}")
    animales     = sb_get("animales",     f"usuario_id=eq.{user_id}")
    reproduccion = sb_get("reproduccion", f"usuario_id=eq.{user_id}")
    pesajes      = sb_get("pesajes",      f"usuario_id=eq.{user_id}")
    bajas        = sb_get("bajas",        f"usuario_id=eq.{user_id}")
    insumos      = sb_get("insumos",      f"usuario_id=eq.{user_id}")

    data = {
        "usuario_id": user_id,
        "datos": {
            "lotes":        lotes,
            "ventas":       ventas,
            "gastos":       gastos,
            "sanitario":    sanitario,
            "produccion":   produccion,
            "animales":     animales,
            "reproduccion": reproduccion,
            "pesajes":      pesajes,
            "bajas":        bajas,
            "insumos":      insumos,
        },
        "fecha":      str(datetime.datetime.now()),
        "etiqueta":   etiqueta or "",
        "automatico": automatico,
    }

    res = sb_post("respaldo", data)
    print("BACKUP STATUS:", res.status_code)


def hay_datos(user_id):
    """Retorna True si el usuario tiene al menos un registro en cualquier tabla."""
    return bool(
        sb_get("lotes",    f"usuario_id=eq.{user_id}&limit=1") or
        sb_get("ventas",   f"usuario_id=eq.{user_id}&limit=1") or
        sb_get("gastos",   f"usuario_id=eq.{user_id}&limit=1") or
        sb_get("animales", f"usuario_id=eq.{user_id}&limit=1") or
        sb_get("insumos",  f"usuario_id=eq.{user_id}&limit=1")
    )


# Minutos dentro de los cuales NO se repite el backup automático.
# Evita disparar ~16 round-trips a Supabase en cada operación cuando el usuario
# hace varias ediciones seguidas. Un snapshot de hace pocos minutos sigue siendo
# un punto de restauración válido (contiene los datos previos a la operación).
_THROTTLE_MIN = 3


def _backup_reciente(user_id) -> bool:
    """True si ya existe un backup automático dentro de la ventana de throttle."""
    try:
        ult = sb_get(
            "respaldo",
            f"usuario_id=eq.{user_id}&automatico=eq.true"
            f"&order=fecha.desc&limit=1&select=fecha",   # solo fecha, no el JSON completo
        )
        if not ult:
            return False
        ult_dt = datetime.datetime.fromisoformat(ult[0].get("fecha", ""))
        # Normaliza a naive para poder comparar con datetime.now()
        if ult_dt.tzinfo is not None:
            ult_dt = ult_dt.replace(tzinfo=None)
        return (datetime.datetime.now() - ult_dt) < datetime.timedelta(minutes=_THROTTLE_MIN)
    except Exception:
        return False   # ante cualquier duda, no bloquear el backup


def backup_automatico(user_id):
    """Hace backup silencioso antes de operaciones destructivas (con throttle)."""
    try:
        if _backup_reciente(user_id):
            print("⏭ Backup automático omitido (ya hay uno reciente)")
            return
        if hay_datos(user_id):
            print("⚡ BACKUP AUTOMÁTICO")
            hacer_backup(user_id, automatico=True)
    except Exception as e:
        print("❌ Error en backup automático:", e)