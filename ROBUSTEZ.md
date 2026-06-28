# Robustez y concurrencia — ERP Pecuario

Notas de los cambios para soportar muchos usuarios simultáneos sin romperse.

## ✅ Aplicado en código

### 1. Pool de conexiones HTTP + reintentos (`config.py`)
Antes cada llamada a Supabase abría un socket nuevo. Ahora se usa una
`requests.Session` compartida con `HTTPAdapter` (keep-alive, pool de hasta 50
conexiones) y reintentos automáticos **solo en GET** (idempotente) ante errores
transitorios 502/503/504. Esto multiplica el throughput bajo carga y evita
caídas por agotamiento de conexiones.

### 2. Concurrencia del servidor (`procfile` y `render.YAML`)
Gunicorn pasa de `--workers 2` (2 peticiones simultáneas) a
`--workers 2 --threads 8 --worker-class gthread --timeout 60`
(~16 peticiones simultáneas). La app es I/O-bound (espera a Supabase), así que
los hilos dan concurrencia real. `timeout` sube a 60s para no matar operaciones
lentas bajo carga.

### 3. Throttle de backups automáticos (`backup_utils.py`)
`backup_automatico()` disparaba ~16 round-trips a Supabase en **cada** operación
destructiva (10 GET + POST con copia completa + 5 GET de `hay_datos`). Ahora, si
ya existe un backup automático de hace menos de `_THROTTLE_MIN` (3) minutos, se
omite. Sigue siendo un punto de restauración válido (el snapshot reciente
contiene los datos previos), pero elimina la mayor parte de la carga en ráfagas
de edición.

## ✅ Resuelto — condición de carrera en el stock de lotes (lost update)

Antes, `ventas.py` y `bajas.py` hacían **read-modify-write** sobre
`cantidad_actual` (leer, sumar/restar, reescribir) → dos operaciones simultáneas
sobre el mismo lote podían pisarse y dejar el conteo mal.

**Ya está resuelto:** se creó la función `descontar_lote` en Supabase y los
**6 sitios** (venta de animal, venta de lote, dos reversiones al eliminar venta,
registrar baja y reversión de baja) ahora llaman a un **decremento atómico** vía
`sb_rpc("descontar_lote", ...)`. Las reposiciones usan `p_cantidad` negativo.
El helper `sb_rpc` está en `config.py`.

Función desplegada (referencia):

```sql
create or replace function descontar_lote(
    p_lote_id   bigint,
    p_owner_id  bigint,
    p_cantidad  int default 1
) returns void
language sql
as $$
  update lotes
     set cantidad_actual = greatest(0, cantidad_actual - p_cantidad),
         activo          = (greatest(0, cantidad_actual - p_cantidad) > 0)
   where id = p_lote_id
     and usuario_id = p_owner_id;
$$;
```

> Si en el futuro agregas otro ajuste de stock (p. ej. insumos), usa el mismo
> patrón: `sb_rpc("descontar_lote", {...})` con `p_cantidad` positivo para
> descontar o negativo para reponer.

## ⏳ Pendiente — requiere acción en Supabase

### B. Retención de la tabla `respaldo`
Cada backup guarda una copia JSON completa de todos los datos del usuario. Sin
limpieza, la tabla crece sin límite. Recomendado: un job que conserve solo los
últimos N backups por usuario, p. ej.:

```sql
-- Conserva los 10 backups más recientes por usuario
delete from respaldo r
 where r.id not in (
   select id from (
     select id, row_number() over (
       partition by usuario_id order by fecha desc
     ) as rn
     from respaldo
   ) t where rn <= 10
 );
```

### C. Rate limiting distribuido
El rate limiting de login (usuarios y admin) es **en memoria por worker/hilo**.
Con varios workers/instancias el límite real es más laxo. Para un límite estricto
hay que moverlo a una tabla de Supabase o a Redis. Aceptable para el volumen
actual; tenerlo presente al escalar.
