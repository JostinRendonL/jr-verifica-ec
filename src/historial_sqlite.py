"""
Historial + Caché persistente en SQLite.

Drop-in replacement de historial.py (mismo API público) usando sqlite3 stdlib.

Mejoras vs JSON:
- Sin límite de 5000 entradas (antes se truncaba silenciosamente)
- Lectura indexada por cédula/timestamp/semaforo (queries 10-100x más rápidas)
- Escritura solo del registro nuevo (no se reescribe todo el archivo)
- WAL mode: múltiples lectores + 1 escritor concurrente
- Auto-migración del historial.json legacy al primer arranque

Schema:
    historial(id, cedula, tipo, timestamp, semaforo, nombre, resultado_json)
    + índices por (cedula,ts), ts, semaforo

API pública (idéntica a historial.py):
    buscar_cache, registrar, listar, obtener_resultado, total_entradas,
    borrar_entrada, borrar_por_cedula, limpiar_todo, calcular_stats,
    CACHE_TTL_SEG
"""
from __future__ import annotations

import os
import json
import time
import uuid
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Config ───────────────────────────────────────────────────────────────────
CACHE_TTL_SEG = int(os.getenv("CACHE_TTL_SEG", str(60 * 60 * 24)))   # 24h default

_DATA_DIR  = Path(os.getenv("DATA_DIR", "/app/data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_FILE   = _DATA_DIR / "historial.db"
_JSON_LEGACY = _DATA_DIR / "historial.json"

# Lock para escrituras (sqlite3 WAL permite muchos lectores + 1 escritor)
_write_lock = threading.Lock()

# Conexión singleton — sqlite3 puede compartirse entre threads si
# check_same_thread=False y usamos lock en escrituras.
_conn: sqlite3.Connection | None = None


# ── Schema + init ────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS historial (
    id              TEXT PRIMARY KEY,
    cedula          TEXT NOT NULL,
    tipo            TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    semaforo        TEXT,
    nombre          TEXT,
    resultado_json  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cedula_ts ON historial(cedula, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ts        ON historial(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_semaforo  ON historial(semaforo);
"""


def _get_conn() -> sqlite3.Connection:
    """Lazy singleton de la conexión SQLite. WAL mode + thread-safe."""
    global _conn
    if _conn is not None:
        return _conn

    _conn = sqlite3.connect(
        str(_DB_FILE),
        check_same_thread=False,   # permitir uso desde múltiples threads
        timeout=30.0,              # esperar hasta 30s si otro thread tiene el lock
        isolation_level=None,      # autocommit (manejamos transacciones explícitas)
    )
    _conn.row_factory = sqlite3.Row

    # WAL = Write-Ahead Logging: lectores no se bloquean por escritor
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=NORMAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(_SCHEMA)

    # ── Migración: agregar lote_id y lote_nombre si no existen ──────────
    cols = {r["name"] for r in _conn.execute("PRAGMA table_info(historial)")}
    if "lote_id" not in cols:
        _conn.execute("ALTER TABLE historial ADD COLUMN lote_id TEXT")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_lote ON historial(lote_id)")
    if "lote_nombre" not in cols:
        _conn.execute("ALTER TABLE historial ADD COLUMN lote_nombre TEXT")
    if "usuario_id" not in cols:
        _conn.execute("ALTER TABLE historial ADD COLUMN usuario_id TEXT")
    if "notas" not in cols:
        _conn.execute("ALTER TABLE historial ADD COLUMN notas TEXT")

    print(f"[historial_sqlite] ✅ conectado a {_DB_FILE} (WAL mode)")
    return _conn


def _migrar_desde_json_si_existe() -> None:
    """
    Si hay un historial.json legacy y la DB está vacía, migra los datos.
    Después renombra el JSON a .migrated para no re-procesarlo.
    """
    if not _JSON_LEGACY.exists():
        return

    conn = _get_conn()
    cur = conn.execute("SELECT COUNT(*) FROM historial")
    existing = cur.fetchone()[0]
    if existing > 0:
        # DB ya tiene datos — el JSON es de un run anterior, archivar
        archivo_arch = _JSON_LEGACY.with_suffix(".json.migrated")
        try:
            _JSON_LEGACY.rename(archivo_arch)
            print(f"[historial_sqlite] DB ya tenía {existing} entradas — JSON archivado a {archivo_arch.name}")
        except Exception as e:
            print(f"[historial_sqlite] no se pudo archivar JSON: {e}")
        return

    try:
        print(f"[historial_sqlite] 🚚 migrando {_JSON_LEGACY.name} → SQLite...")
        with open(_JSON_LEGACY, "r", encoding="utf-8") as f:
            entradas = json.load(f)

        rows = []
        for e in entradas:
            rows.append((
                e.get("id", ""),
                e.get("cedula", ""),
                e.get("tipo", ""),
                int(e.get("timestamp", 0)),
                e.get("semaforo", ""),
                e.get("nombre", ""),
                json.dumps(e.get("resultado", {}), ensure_ascii=False),
            ))

        with _write_lock:
            conn.execute("BEGIN")
            try:
                conn.executemany(
                    "INSERT OR IGNORE INTO historial "
                    "(id, cedula, tipo, timestamp, semaforo, nombre, resultado_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        print(f"[historial_sqlite] ✅ migradas {len(rows)} entradas")

        # Archivar el JSON original como backup
        archivo_arch = _JSON_LEGACY.with_suffix(".json.migrated")
        _JSON_LEGACY.rename(archivo_arch)
        print(f"[historial_sqlite] JSON archivado a {archivo_arch.name}")
    except Exception as e:
        print(f"[historial_sqlite] ❌ ERROR migrando JSON: {e} — DB queda vacía pero JSON intacto")


# Init al importar
_get_conn()
_migrar_desde_json_si_existe()


# ── API pública (compatible con historial.py legacy) ─────────────────────────

def buscar_cache(cedula: str, tipo: str) -> Optional[dict]:
    """
    Si existe una entrada para esta cédula+tipo dentro del TTL, retornar
    el resultado. Si tipo='bachiller' o 'satje', un 'completo' válido también sirve.
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return None

    ahora = int(time.time())
    cutoff = ahora - CACHE_TTL_SEG

    # Buscar tipo exacto primero, luego 'completo' como fallback para sub-tipos
    tipos_a_buscar = [tipo]
    if tipo in ("bachiller", "satje"):
        tipos_a_buscar.append("completo")

    conn = _get_conn()
    placeholders = ",".join("?" * len(tipos_a_buscar))
    cur = conn.execute(
        f"SELECT resultado_json FROM historial "
        f"WHERE cedula = ? AND tipo IN ({placeholders}) AND timestamp >= ? "
        f"ORDER BY timestamp DESC LIMIT 1",
        (cedula, *tipos_a_buscar, cutoff),
    )
    row = cur.fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["resultado_json"])
    except Exception as e:
        print(f"[historial_sqlite] error parseando resultado_json: {e}")
        return None


def registrar(resultado: dict, tipo: str, usuario_id: Optional[str] = None,
              lote_id: Optional[str] = None, lote_nombre: Optional[str] = None) -> None:
    """Agrega una entrada al historial y la persiste.

    `usuario_id` es opcional para retrocompatibilidad.
    `lote_id` y `lote_nombre` son opcionales — solo se usan en procesamiento
    por lote para agrupar visualmente las entradas del mismo Excel.
    """
    entrada_id = f"{int(time.time() * 1000):x}{uuid.uuid4().hex[:8]}"
    cedula     = resultado.get("cedula", "")
    timestamp  = int(time.time())
    semaforo   = resultado.get("semaforo", "")
    nombre     = (
        resultado.get("nombre")
        or (resultado.get("bachiller") or {}).get("nombre", "")
        or ""
    )
    resultado_json = json.dumps(resultado, ensure_ascii=False)

    conn = _get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(historial)")}
    tiene_usuario_id = "usuario_id" in cols
    tiene_lote       = "lote_id" in cols

    with _write_lock:
        if tiene_usuario_id and tiene_lote:
            conn.execute(
                "INSERT OR REPLACE INTO historial "
                "(id, cedula, tipo, timestamp, semaforo, nombre, resultado_json, usuario_id, lote_id, lote_nombre) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entrada_id, cedula, tipo, timestamp, semaforo, nombre,
                 resultado_json, usuario_id, lote_id, lote_nombre),
            )
        elif tiene_usuario_id:
            conn.execute(
                "INSERT OR REPLACE INTO historial "
                "(id, cedula, tipo, timestamp, semaforo, nombre, resultado_json, usuario_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entrada_id, cedula, tipo, timestamp, semaforo, nombre,
                 resultado_json, usuario_id),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO historial "
                "(id, cedula, tipo, timestamp, semaforo, nombre, resultado_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entrada_id, cedula, tipo, timestamp, semaforo, nombre, resultado_json),
            )


def obtener_lotes(limite: int = 50) -> list[dict]:
    """Lista todos los lotes con stats agregadas: total, semáforos, primer/último ts."""
    conn = _get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(historial)")}
    if "lote_id" not in cols:
        return []
    cur = conn.execute(
        """
        SELECT
            lote_id,
            MAX(COALESCE(lote_nombre, '')) AS lote_nombre,
            MIN(timestamp)                  AS iniciado,
            MAX(timestamp)                  AS terminado,
            COUNT(*)                        AS total,
            SUM(CASE WHEN UPPER(COALESCE(semaforo,'')) LIKE '%APTO%'         THEN 1 ELSE 0 END) AS n_apto,
            SUM(CASE WHEN UPPER(COALESCE(semaforo,'')) LIKE '%OBSERVACI%'    THEN 1 ELSE 0 END) AS n_obs,
            SUM(CASE WHEN UPPER(COALESCE(semaforo,'')) LIKE '%RECHAZAR%'     THEN 1 ELSE 0 END) AS n_rech,
            SUM(CASE WHEN UPPER(COALESCE(semaforo,'')) LIKE '%CR_TICO%'      THEN 1 ELSE 0 END) AS n_crit,
            SUM(CASE WHEN UPPER(COALESCE(semaforo,'')) LIKE '%SIN DATOS%'    THEN 1 ELSE 0 END) AS n_sin,
            usuario_id
        FROM historial
        WHERE lote_id IS NOT NULL AND lote_id != ''
        GROUP BY lote_id
        ORDER BY MAX(timestamp) DESC
        LIMIT ?
        """,
        (int(limite),),
    )
    rows = []
    for r in cur.fetchall():
        rows.append({
            "lote_id":     r["lote_id"],
            "lote_nombre": r["lote_nombre"] or "(sin nombre)",
            "iniciado":    r["iniciado"],
            "terminado":   r["terminado"],
            "total":       r["total"],
            "n_apto":      r["n_apto"],
            "n_obs":       r["n_obs"],
            "n_rech":      r["n_rech"],
            "n_crit":      r["n_crit"],
            "n_sin":       r["n_sin"],
            "usuario_id":  r["usuario_id"],
        })
    return rows


_ORDEN_VALIDOS = {
    "fecha-desc":   "{ts} DESC",
    "fecha-asc":    "{ts} ASC",
    "nombre-asc":   "UPPER(COALESCE({nom},'')) ASC, {ts} DESC",
    "nombre-desc":  "UPPER(COALESCE({nom},'')) DESC, {ts} DESC",
    "cedula-asc":   "{ced} ASC, {ts} DESC",
    "cedula-desc":  "{ced} DESC, {ts} DESC",
    # Orden semáforo: APTO → OBSERVACIÓN → RECHAZAR → CRÍTICO → SIN DATOS
    # Usa CASE WHEN para mapear semáforo a un número de prioridad.
    "semaforo":     ("CASE "
                     "WHEN UPPER(COALESCE({sem},'')) LIKE '%APTO%'          THEN 1 "
                     "WHEN UPPER(COALESCE({sem},'')) LIKE '%OBSERVACI%'     THEN 2 "
                     "WHEN UPPER(COALESCE({sem},'')) LIKE '%RECHAZAR%'      THEN 3 "
                     "WHEN UPPER(COALESCE({sem},'')) LIKE '%CR_TICO%'       THEN 4 "
                     "ELSE 5 END ASC, {ts} DESC"),
}


def listar(filtro_cedula: str = "", filtro_semaforo: str = "",
           filtro_usuario_id: str = "", filtro_nombre: str = "",
           filtro_lote_id: str = "",
           dedup_por_cedula: bool = False,
           orden: str = "fecha-desc",
           limite: int = 200) -> list[dict]:
    """Devuelve las entradas más recientes (sin resultado completo).

    Incluye el nombre del operador (LEFT JOIN con usuarios) si la columna
    `usuario_id` existe en la tabla historial. Filas pre-migración tienen
    `usuario_id = NULL` → se devuelven como operador_nombre = '—'.
    """
    cedula_f   = (filtro_cedula or "").strip()
    semaforo_f = (filtro_semaforo or "").strip().upper()
    usuario_f  = (filtro_usuario_id or "").strip()
    nombre_f   = (filtro_nombre or "").strip()
    lote_f     = (filtro_lote_id or "").strip()

    conn = _get_conn()
    # Detectar si la columna usuario_id existe (compatibilidad pre-migración)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(historial)")}
    tiene_usuario_id = "usuario_id" in cols
    # Detectar si existe la tabla usuarios (para el JOIN)
    tiene_usuarios = bool(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usuarios'"
    ).fetchone())

    # Detectar lote_id (post-migración)
    tiene_lote = "lote_id" in cols

    if tiene_usuario_id and tiene_usuarios:
        lote_select = ", h.lote_id, h.lote_nombre" if tiene_lote else ", NULL AS lote_id, NULL AS lote_nombre"
        sql = (f"SELECT h.id, h.cedula, h.tipo, h.timestamp, h.semaforo, h.nombre, "
               f"       h.usuario_id, u.nombre AS operador_nombre, u.email AS operador_email"
               f"{lote_select} "
               f"FROM historial h LEFT JOIN usuarios u ON u.id = h.usuario_id "
               f"WHERE 1=1")
    else:
        lote_select = ", lote_id, lote_nombre" if tiene_lote else ", NULL AS lote_id, NULL AS lote_nombre"
        sql = (f"SELECT id, cedula, tipo, timestamp, semaforo, nombre, "
               f"       NULL AS usuario_id, NULL AS operador_nombre, NULL AS operador_email"
               f"{lote_select} "
               f"FROM historial WHERE 1=1")

    params: list = []

    if cedula_f:
        sql += " AND " + ("h.cedula" if tiene_usuario_id and tiene_usuarios else "cedula") + " LIKE ?"
        params.append(f"%{cedula_f}%")
    if semaforo_f:
        sql += " AND UPPER(" + ("h.semaforo" if tiene_usuario_id and tiene_usuarios else "semaforo") + ") LIKE ?"
        params.append(f"%{semaforo_f}%")
    if usuario_f and tiene_usuario_id:
        sql += " AND h.usuario_id = ?"
        params.append(usuario_f)
    if nombre_f:
        # Búsqueda por nombre: ignora orden de palabras (cada token con LIKE).
        # Ej: 'perez juan' encuentra 'JUAN CARLOS PEREZ MENDOZA'.
        col = "h.nombre" if tiene_usuario_id and tiene_usuarios else "nombre"
        for token in nombre_f.split():
            sql += f" AND UPPER(COALESCE({col},'')) LIKE ?"
            params.append(f"%{token.upper()}%")
    if lote_f:
        col = "h.lote_id" if tiene_usuario_id and tiene_usuarios else "lote_id"
        if lote_f == "__individuales__":
            sql += f" AND ({col} IS NULL OR {col} = '')"
        else:
            sql += f" AND {col} = ?"
            params.append(lote_f)

    ts_col  = "h.timestamp" if tiene_usuario_id and tiene_usuarios else "timestamp"
    nom_col = "h.nombre"    if tiene_usuario_id and tiene_usuarios else "nombre"
    ced_col = "h.cedula"    if tiene_usuario_id and tiene_usuarios else "cedula"
    sem_col = "h.semaforo"  if tiene_usuario_id and tiene_usuarios else "semaforo"

    # Resolver ORDER BY según `orden` (whitelist segura — protege de SQL injection)
    orden_key = orden if orden in _ORDEN_VALIDOS else "fecha-desc"
    order_by_sql = _ORDEN_VALIDOS[orden_key].format(
        ts=ts_col, nom=nom_col, ced=ced_col, sem=sem_col
    )

    if dedup_por_cedula:
        # CTE: solo la entrada mas reciente por cedula + conteo total.
        # Para dedup mantenemos PARTITION ORDER BY timestamp DESC (queremos la
        # mas reciente), pero el ORDER BY del SELECT externo respeta el orden pedido.
        # Mapear las columnas dentro del CTE (sin alias h.) para el ORDER BY externo.
        outer_order = _ORDEN_VALIDOS[orden_key].format(
            ts="timestamp", nom="nombre", ced="cedula", sem="semaforo"
        )
        sql_dedup = (
            "WITH ranked AS ( "
            + sql.replace("SELECT ", "SELECT "
                f"ROW_NUMBER() OVER (PARTITION BY {ced_col} "
                f"ORDER BY {ts_col} DESC) AS rn, "
                f"COUNT(*) OVER (PARTITION BY {ced_col}) AS verif_count, ", 1)
            + f") SELECT * FROM ranked WHERE rn = 1 ORDER BY {outer_order} LIMIT ?"
        )
        params.append(limite)
        cur = conn.execute(sql_dedup, params)
    else:
        sql += f" ORDER BY {order_by_sql} LIMIT ?"
        params.append(limite)
        cur = conn.execute(sql, params)

    ahora = int(time.time())
    rows = []
    for r in cur.fetchall():
        rows.append({
            "id":              r["id"],
            "cedula":          r["cedula"],
            "tipo":            r["tipo"],
            "timestamp":       r["timestamp"],
            "semaforo":        r["semaforo"],
            "nombre":          r["nombre"],
            "edad_seg":        ahora - r["timestamp"],
            "usuario_id":      r["usuario_id"],
            "operador_nombre": r["operador_nombre"] or "—",
            "operador_email":  r["operador_email"]  or "",
            "lote_id":         r["lote_id"],
            "lote_nombre":     r["lote_nombre"],
            "verif_count":     r["verif_count"] if dedup_por_cedula else 1,
        })
    return rows


def cedulas_con_errores_lote(lote_id: str) -> list[dict]:
    """Devuelve cédulas de un lote cuyas verificaciones contienen ERROR.
    Útil para "re-procesar vacíos" antes de exportar.
    Retorna: [{cedula, nombre, fuentes_con_error: [...]}]"""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, cedula, nombre, resultado_json, semaforo FROM historial "
        "WHERE lote_id = ?", (lote_id,)
    )
    con_errores = []
    for row in cur.fetchall():
        try:
            res = json.loads(row["resultado_json"]) if row["resultado_json"] else {}
        except Exception:
            continue
        errores = []
        b = (res.get("bachiller") or {})
        s = (res.get("satje") or {})
        st = (res.get("setec") or {})
        fi = (res.get("fiscalia") or {})
        if b and (b.get("estado") == "ERROR"):                   errores.append("bachiller")
        if s and (s.get("status") == "ERROR" or s.get("estado") == "ERROR"): errores.append("satje")
        if st and (st.get("estado") == "ERROR"):                 errores.append("setec")
        if fi and (fi.get("estado") == "ERROR"):                 errores.append("fiscalia")
        if errores:
            con_errores.append({
                "id":     row["id"],
                "cedula": row["cedula"],
                "nombre": row["nombre"] or "",
                "fuentes_con_error": errores,
            })
    return con_errores


def listar_por_cedula(cedula: str, limite: int = 50) -> list[dict]:
    """Devuelve todas las verificaciones de una cédula (para vista expandida)."""
    cedula = (cedula or "").strip()
    if not cedula:
        return []
    conn = _get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(historial)")}
    tiene_lote = "lote_id" in cols
    extra = ", lote_id, lote_nombre" if tiene_lote else ", NULL AS lote_id, NULL AS lote_nombre"
    cur = conn.execute(
        f"SELECT id, cedula, tipo, timestamp, semaforo, nombre {extra} "
        f"FROM historial WHERE cedula = ? ORDER BY timestamp DESC LIMIT ?",
        (cedula, int(limite)),
    )
    ahora = int(time.time())
    return [{
        "id":          r["id"],
        "cedula":      r["cedula"],
        "tipo":        r["tipo"],
        "timestamp":   r["timestamp"],
        "edad_seg":    ahora - r["timestamp"],
        "semaforo":    r["semaforo"],
        "nombre":      r["nombre"],
        "lote_id":     r["lote_id"],
        "lote_nombre": r["lote_nombre"],
    } for r in cur.fetchall()]


def obtener_resultado(id_entrada: str) -> Optional[dict]:
    """Trae el resultado completo de una entrada por ID."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, cedula, tipo, timestamp, semaforo, nombre, resultado_json "
        "FROM historial WHERE id = ?",
        (id_entrada,),
    )
    row = cur.fetchone()
    if row is None:
        return None

    try:
        resultado = json.loads(row["resultado_json"])
    except Exception:
        resultado = {}

    return {
        "id":        row["id"],
        "cedula":    row["cedula"],
        "tipo":      row["tipo"],
        "timestamp": row["timestamp"],
        "semaforo":  row["semaforo"],
        "nombre":    row["nombre"],
        "resultado": resultado,
        "edad_seg":  int(time.time()) - row["timestamp"],
    }


def total_entradas() -> int:
    conn = _get_conn()
    cur = conn.execute("SELECT COUNT(*) FROM historial")
    return cur.fetchone()[0]


def actualizar_nombre(cedula: str, nombre: str) -> bool:
    """
    Actualiza el nombre en la entrada más reciente de una cédula.
    También lo escribe dentro de resultado_json para que el cache
    lo devuelva con nombre en búsquedas futuras.
    Retorna True si actualizó al menos una fila.
    """
    cedula = (cedula or "").strip()
    nombre = (nombre or "").strip()
    if not cedula:
        return False

    conn = _get_conn()
    # Buscar la entrada más reciente de esta cédula
    cur = conn.execute(
        "SELECT id, resultado_json FROM historial "
        "WHERE cedula = ? ORDER BY timestamp DESC LIMIT 1",
        (cedula,),
    )
    row = cur.fetchone()
    if row is None:
        return False

    # Actualizar nombre dentro del resultado_json
    try:
        resultado = json.loads(row["resultado_json"])
    except Exception:
        resultado = {}
    resultado["nombre"] = nombre
    resultado_json_nuevo = json.dumps(resultado, ensure_ascii=False)

    with _write_lock:
        conn.execute(
            "UPDATE historial SET nombre = ?, resultado_json = ? WHERE id = ?",
            (nombre, resultado_json_nuevo, row["id"]),
        )
    return True


def actualizar_notas(cedula: str, notas: str) -> bool:
    """Guarda notas (texto libre) en TODAS las entradas de una cédula. Las notas
    son del operador, no se sobrescriben con re-verificaciones."""
    cedula = (cedula or "").strip()
    notas  = (notas or "").strip()[:2000]  # tope 2k chars
    if not cedula:
        return False
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "UPDATE historial SET notas = ? WHERE cedula = ?",
            (notas or None, cedula),
        )
    return cur.rowcount > 0


def obtener_notas(cedula: str) -> str:
    cedula = (cedula or "").strip()
    if not cedula:
        return ""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT notas FROM historial WHERE cedula = ? AND notas IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 1",
        (cedula,),
    )
    row = cur.fetchone()
    return (row["notas"] or "").strip() if row else ""


def obtener_nombre_guardado(cedula: str) -> str:
    """
    Retorna el nombre de la entrada más reciente de una cédula, sin importar TTL.
    Útil para preservar nombres editados manualmente al re-verificar.
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return ""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT nombre FROM historial WHERE cedula = ? ORDER BY timestamp DESC LIMIT 1",
        (cedula,),
    )
    row = cur.fetchone()
    return (row["nombre"] or "").strip() if row else ""


def obtener_semaforo_manual(cedula: str) -> str | None:
    """
    Retorna el semáforo guardado manualmente para una cédula (campo semaforo_manual
    en resultado_json), o None si nunca fue modificado manualmente.
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return None
    conn = _get_conn()
    cur = conn.execute(
        "SELECT resultado_json FROM historial WHERE cedula = ? ORDER BY timestamp DESC LIMIT 1",
        (cedula,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    try:
        resultado = json.loads(row["resultado_json"])
    except Exception:
        return None
    if resultado.get("semaforo_manual"):
        return resultado.get("semaforo", None)
    return None


def actualizar_semaforo(cedula: str, semaforo: str) -> bool:
    """
    Guarda un semáforo manualmente para una cédula.
    Marca resultado_json['semaforo_manual'] = True para que el re-verificado
    no lo sobreescriba con el valor calculado automáticamente.
    Retorna True si actualizó al menos una fila.
    """
    SEMAFOROS_VALIDOS = {
        "APTO":       "🟢 APTO",
        "OBSERVACION": "🟡 OBSERVACIÓN",
        "OBSERVACIÓN": "🟡 OBSERVACIÓN",
        "RECHAZAR":   "🔴 RECHAZAR",
        "CRITICO":    "🚨 CRÍTICO",
        "CRÍTICO":    "🚨 CRÍTICO",
    }
    cedula   = (cedula or "").strip()
    semaforo = (semaforo or "").strip().upper()
    if not cedula or semaforo not in SEMAFOROS_VALIDOS:
        return False
    semaforo_fmt = SEMAFOROS_VALIDOS[semaforo]

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, resultado_json FROM historial WHERE cedula = ? ORDER BY timestamp DESC LIMIT 1",
        (cedula,),
    )
    row = cur.fetchone()
    if row is None:
        return False

    try:
        resultado = json.loads(row["resultado_json"])
    except Exception:
        resultado = {}
    resultado["semaforo"]        = semaforo_fmt
    resultado["semaforo_manual"] = True
    resultado_json_nuevo = json.dumps(resultado, ensure_ascii=False)

    with _write_lock:
        conn.execute(
            "UPDATE historial SET semaforo = ?, resultado_json = ? WHERE id = ?",
            (semaforo_fmt, resultado_json_nuevo, row["id"]),
        )
    return True


def actualizar_fiscalia_manual(cedula: str, estado: str, detalle: str,
                                operador_email: str = "", operador_nombre: str = "") -> bool:
    """
    Marca Fiscalia como verificada manualmente cuando el scraper automatico falla.
    Modifica resultado_json para reemplazar fiscalia.estado=ERROR por una
    verificacion manual con estado SIN_ANTECEDENTES o SOSPECHOSO/DENUNCIANTE,
    y deja un registro de quien/cuando lo verifico manualmente.

    Tambien actualiza el semaforo si correspondiera (depende del nuevo estado).
    """
    import time
    ESTADOS_VALIDOS = {
        "SIN_ANTECEDENTES": "SIN_ANTECEDENTES",
        "SOSPECHOSO":       "SOSPECHOSO",
        "DENUNCIANTE":      "DENUNCIANTE",
    }
    cedula = (cedula or "").strip()
    est = (estado or "").strip().upper()
    if not cedula or est not in ESTADOS_VALIDOS:
        return False
    estado_fmt = ESTADOS_VALIDOS[est]

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, resultado_json, semaforo FROM historial WHERE cedula = ? ORDER BY timestamp DESC LIMIT 1",
        (cedula,),
    )
    row = cur.fetchone()
    if row is None:
        return False

    try:
        resultado = json.loads(row["resultado_json"])
    except Exception:
        resultado = {}

    # Reemplazar fiscalia con la verificacion manual
    resultado["fiscalia"] = {
        "estado":           estado_fmt,
        "como_sospechoso":  1 if estado_fmt == "SOSPECHOSO" else 0,
        "como_denunciante": 1 if estado_fmt == "DENUNCIANTE" else 0,
        "noticias":         [],
        "detalle":          (detalle or "").strip()[:500],
        "manual": {
            "verificado":      True,
            "operador_email":  operador_email or "",
            "operador_nombre": operador_nombre or "",
            "timestamp":       int(time.time()),
        },
    }

    resultado_json_nuevo = json.dumps(resultado, ensure_ascii=False)

    with _write_lock:
        conn.execute(
            "UPDATE historial SET resultado_json = ? WHERE id = ?",
            (resultado_json_nuevo, row["id"]),
        )
    return True


def borrar_entrada(id_entrada: str) -> bool:
    """Elimina UNA entrada del historial. True si la borró."""
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute("DELETE FROM historial WHERE id = ?", (id_entrada,))
    return cur.rowcount > 0


def borrar_multiples(ids: list[str]) -> int:
    """Elimina varias entradas por ID en una transacción. Devuelve cuántas borró."""
    ids = [i.strip() for i in (ids or []) if i and i.strip()]
    if not ids:
        return 0
    conn = _get_conn()
    placeholders = ",".join("?" * len(ids))
    with _write_lock:
        cur = conn.execute(
            f"DELETE FROM historial WHERE id IN ({placeholders})",
            tuple(ids),
        )
    return cur.rowcount


def borrar_por_cedula(cedula: str) -> int:
    """Elimina TODAS las entradas de una cédula. Devuelve cuántas borró."""
    cedula = (cedula or "").strip()
    if not cedula:
        return 0
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute("DELETE FROM historial WHERE cedula = ?", (cedula,))
    return cur.rowcount


def limpiar_todo() -> int:
    """Borra TODO el historial. Devuelve cuántas entradas había."""
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute("SELECT COUNT(*) FROM historial")
        n = cur.fetchone()[0]
        conn.execute("DELETE FROM historial")
        conn.execute("VACUUM")
    return n


def borrar_antiguos(meses: int = 12) -> int:
    """
    LOPDP — borra entradas con timestamp más viejo que X meses.
    Devuelve cuántas se borraron. Útil como cron periódico.
    """
    if meses <= 0:
        return 0
    cutoff = int(time.time()) - (meses * 30 * 86400)
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute("DELETE FROM historial WHERE timestamp < ?", (cutoff,))
        n = cur.rowcount
        if n > 0:
            # Liberar espacio físico de las páginas borradas
            conn.execute("VACUUM")
    return n


# ── Stats para dashboard ─────────────────────────────────────────────────────

def calcular_stats() -> dict:
    """Métricas agregadas para el dashboard. SQL GROUP BY = mucho más rápido que iterar."""
    ahora    = int(time.time())
    UN_DIA   = 86400
    UNA_SEM  = UN_DIA * 7
    UN_MES   = UN_DIA * 30

    conn = _get_conn()

    # Totales por periodo (1 query)
    cur = conn.execute(
        "SELECT "
        "  COUNT(*)                                                        AS total, "
        "  SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END)                 AS hoy, "
        "  SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END)                 AS semana, "
        "  SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END)                 AS mes "
        "FROM historial",
        (ahora - UN_DIA, ahora - UNA_SEM, ahora - UN_MES),
    )
    r = cur.fetchone()
    total        = r["total"] or 0
    hoy_count    = r["hoy"] or 0
    semana_count = r["semana"] or 0
    mes_count    = r["mes"] or 0

    # Niveles (mapeo de etiquetas viejas + nuevas)
    MAPEO_VIEJO = {"VERDE": "APTO", "AMARILLO": "OBSERVACIÓN", "ROJO": "RECHAZAR", "GRIS": "SIN DATOS"}
    niveles = {"APTO": 0, "OBSERVACIÓN": 0, "RECHAZAR": 0, "CRÍTICO": 0, "SIN DATOS": 0, "OTROS": 0}

    cur = conn.execute(
        "SELECT semaforo, resultado_json FROM historial WHERE timestamp >= ?",
        (ahora - UN_MES,),
    )
    delitos_count: dict[str, int] = {}
    instituciones: dict[str, int] = {}
    por_dia: dict[str, int] = {}

    for row in cur.fetchall():
        sem_str = (row["semaforo"] or "").upper()
        for vieja, nueva in MAPEO_VIEJO.items():
            sem_str = sem_str.replace(vieja, nueva)

        # Resultado parseado para extraer delitos + instituciones
        try:
            resultado = json.loads(row["resultado_json"]) if row["resultado_json"] else {}
        except Exception:
            resultado = {}

        # Recalcular semaforo desde resultado si está vacío
        if not sem_str:
            b = resultado.get("bachiller", {}) or {}
            s = resultado.get("satje", {}) or {}
            if b and s:
                if s.get("total_demandado", 0) > 0:
                    sem_str = "RECHAZAR"
                elif b.get("estado") != "ENCONTRADO" or s.get("total_actor", 0) > 0:
                    sem_str = "OBSERVACIÓN"
                else:
                    sem_str = "APTO"

        nivel = "OTROS"
        for k in niveles:
            if k in sem_str:
                nivel = k
                break
        niveles[nivel] = niveles.get(nivel, 0) + 1

        # Delitos
        satje = resultado.get("satje", {}) or {}
        for d in (satje.get("delitos") or []):
            clave = d.upper().strip()[:60]
            if clave:
                delitos_count[clave] = delitos_count.get(clave, 0) + 1

        # Instituciones (de bachiller)
        bachiller = resultado.get("bachiller", {}) or {}
        inst = (bachiller.get("institucion") or "").strip()
        if inst:
            instituciones[inst] = instituciones.get(inst, 0) + 1

    # Series por día (mes — group by SQL)
    cur = conn.execute(
        "SELECT strftime('%d/%m', timestamp, 'unixepoch', 'localtime') AS dia, "
        "       COUNT(*) AS consultas "
        "FROM historial WHERE timestamp >= ? "
        "GROUP BY dia",
        (ahora - UN_MES,),
    )
    por_dia = {row["dia"]: row["consultas"] for row in cur.fetchall()}

    series_dia = []
    for i in range(29, -1, -1):
        ts_dia = ahora - (i * UN_DIA)
        dia_str = datetime.fromtimestamp(ts_dia).strftime("%d/%m")
        series_dia.append({"dia": dia_str, "consultas": por_dia.get(dia_str, 0)})

    top_delitos       = sorted(delitos_count.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_instituciones = sorted(instituciones.items(), key=lambda kv: kv[1], reverse=True)[:10]

    minutos_ahorrados  = total * 15
    horas_ahorradas    = round(minutos_ahorrados / 60, 1)
    valor_ahorrado_usd = round(horas_ahorradas * 5, 2)

    return {
        "total":               total,
        "hoy":                 hoy_count,
        "semana":              semana_count,
        "mes":                 mes_count,
        "niveles":             niveles,
        "top_delitos":         top_delitos,
        "top_instituciones":   top_instituciones,
        "series_dia":          series_dia,
        "horas_ahorradas":     horas_ahorradas,
        "valor_ahorrado_usd":  valor_ahorrado_usd,
    }
