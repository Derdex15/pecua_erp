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


def backup_automatico(user_id):
    """Hace backup silencioso antes de operaciones destructivas."""
    try:
        if hay_datos(user_id):
            print("⚡ BACKUP AUTOMÁTICO")
            hacer_backup(user_id, automatico=True)
    except Exception as e:
        print("❌ Error en backup automático:", e)