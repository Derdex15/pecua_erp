import datetime
from config import sb_get, sb_post


def hacer_backup(user_id, etiqueta="", automatico=False):
    """Crea un snapshot completo de los datos del usuario en la tabla respaldo."""
    print("📦 HACIENDO BACKUP...")

    lotes      = sb_get("lotes",      f"usuario_id=eq.{user_id}")
    ventas     = sb_get("ventas",     f"usuario_id=eq.{user_id}")
    gastos     = sb_get("gastos",     f"usuario_id=eq.{user_id}")
    sanitario  = sb_get("sanitario",  f"usuario_id=eq.{user_id}")
    produccion = sb_get("produccion", f"usuario_id=eq.{user_id}")

    data = {
        "usuario_id": user_id,
        "datos": {
            "lotes":      lotes,
            "ventas":     ventas,
            "gastos":     gastos,
            "sanitario":  sanitario,
            "produccion": produccion,
        },
        "fecha":      str(datetime.datetime.now()),
        "etiqueta":   etiqueta or "",
        "automatico": automatico,
    }

    res = sb_post("respaldo", data)
    print("BACKUP STATUS:", res.status_code)


def hay_datos(user_id):
    """Retorna True si el usuario tiene al menos un registro."""
    lotes  = sb_get("lotes",  f"usuario_id=eq.{user_id}&limit=1")
    ventas = sb_get("ventas", f"usuario_id=eq.{user_id}&limit=1")
    gastos = sb_get("gastos", f"usuario_id=eq.{user_id}&limit=1")
    return bool(lotes or ventas or gastos)


def backup_automatico(user_id):
    """Hace backup silencioso antes de operaciones destructivas."""
    try:
        if hay_datos(user_id):
            print("⚡ BACKUP AUTOMÁTICO")
            hacer_backup(user_id, automatico=True)
    except Exception as e:
        print("❌ Error en backup automático:", e)