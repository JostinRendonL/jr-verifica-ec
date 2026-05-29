"""
audit_log.py — Registro estructurado de acciones administrativas.

Guarda en SQLite cada acción crítica con:
  ts, actor_id, actor_email, accion, target, ip, metadata_json

Útil para auditorías externas, LOPDP, y forense en caso de incidente.

API:
    registrar(actor, accion, target=None, ip=None, **metadata)
    listar(limite=200, actor_id=None, accion=None)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("verifica.audit")

_DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_FILE = _DATA_DIR / "audit.db"

_conn: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    c = sqlite3.connect(str(_DB_FILE), check_same_thread=False, isolation_level=None)
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA synchronous = NORMAL")
    c.row_factory = sqlite3.Row
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          INTEGER NOT NULL,
            actor_id    TEXT,
            actor_email TEXT,
            accion      TEXT NOT NULL,
            target      TEXT,
            ip          TEXT,
            metadata    TEXT
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts        ON audit_log(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor     ON audit_log(actor_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_accion    ON audit_log(accion)")
    _conn = c
    return c


_get_conn()


def registrar(
    actor,
    accion: str,
    target: Optional[str] = None,
    ip: Optional[str] = None,
    **metadata,
) -> None:
    """Registra una acción en el audit log. `actor` es un Usuario o None.
    Nunca lanza — el audit no debe tumbar la app."""
    try:
        actor_id    = getattr(actor, "id", None) if actor else None
        actor_email = getattr(actor, "email", None) if actor else None
        meta_json   = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None
        conn = _get_conn()
        with _write_lock:
            conn.execute(
                "INSERT INTO audit_log (ts, actor_id, actor_email, accion, target, ip, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(time.time()), actor_id, actor_email, accion, target, ip, meta_json),
            )
        logger.info("audit %s actor=%s target=%s", accion, actor_email or actor_id or "—", target or "—")
    except Exception as e:
        logger.warning("audit_log.registrar fallo: %s", e)


def listar(limite: int = 200, actor_id: Optional[str] = None, accion: Optional[str] = None) -> list[dict]:
    """Lista entradas recientes del audit log."""
    conn = _get_conn()
    sql = "SELECT * FROM audit_log WHERE 1=1"
    args: list = []
    if actor_id:
        sql += " AND actor_id = ?"
        args.append(actor_id)
    if accion:
        sql += " AND accion = ?"
        args.append(accion)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(int(limite))
    cur = conn.execute(sql, tuple(args))
    return [dict(r) for r in cur.fetchall()]
