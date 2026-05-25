"""
Reset de contraseña por email — tokens de un solo uso con TTL.

Schema:
  password_resets(
    token_hash TEXT PK,    -- SHA-256 del token (nunca el token plano)
    usuario_id TEXT NOT NULL,
    creado_ts  INTEGER NOT NULL,
    expira_ts  INTEGER NOT NULL,
    usado_ts   INTEGER,    -- NULL = no usado todavía
    ip_origen  TEXT
  )

Seguridad:
  - Token plano = uuid4 hex de 32 chars (alta entropía).
  - DB guarda SHA-256 del token, nunca el plano (si se filtra la DB no se
    pueden usar los tokens directamente).
  - 1 uso único: al marcar usado_ts queda inválido.
  - TTL: 1 hora por defecto.
  - Anti-enumeración: el caller debe responder igual exista o no el email.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
import sqlite3
import threading
from pathlib import Path
from typing import Optional, NamedTuple


# ── Config ──────────────────────────────────────────────────────────────────
_DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_FILE = _DATA_DIR / "historial.db"   # misma DB que usuarios + historial

_write_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

RESET_TOKEN_TTL_SEG = 60 * 60   # 1h


_SCHEMA = """
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash  TEXT PRIMARY KEY,
    usuario_id  TEXT NOT NULL,
    creado_ts   INTEGER NOT NULL,
    expira_ts   INTEGER NOT NULL,
    usado_ts    INTEGER,
    ip_origen   TEXT
);
CREATE INDEX IF NOT EXISTS idx_pwd_resets_uid    ON password_resets(usuario_id);
CREATE INDEX IF NOT EXISTS idx_pwd_resets_expira ON password_resets(expira_ts);
"""


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    _conn = sqlite3.connect(
        str(_DB_FILE),
        check_same_thread=False,
        timeout=30.0,
        isolation_level=None,
    )
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=NORMAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(_SCHEMA)
    return _conn


def init_db() -> None:
    _get_conn()


def _hash_token(token_plano: str) -> str:
    return hashlib.sha256(token_plano.encode("utf-8")).hexdigest()


# ── API pública ─────────────────────────────────────────────────────────────
class TokenInfo(NamedTuple):
    usuario_id: str
    expira_ts: int
    usado: bool


def generar_token(usuario_id: str, ip_origen: Optional[str] = None,
                  ttl_seg: int = RESET_TOKEN_TTL_SEG) -> str:
    """
    Genera y persiste un token de reset. Devuelve el TOKEN PLANO
    (solo se ve una vez — la DB guarda el hash).
    """
    if not usuario_id:
        raise ValueError("usuario_id requerido")

    init_db()
    token_plano = secrets.token_urlsafe(32)   # ~43 chars URL-safe
    token_hash  = _hash_token(token_plano)
    ahora = int(time.time())
    expira = ahora + ttl_seg

    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO password_resets "
            "(token_hash, usuario_id, creado_ts, expira_ts, usado_ts, ip_origen) "
            "VALUES (?, ?, ?, ?, NULL, ?)",
            (token_hash, usuario_id, ahora, expira, ip_origen),
        )
    return token_plano


def validar_token(token_plano: str) -> Optional[TokenInfo]:
    """Devuelve info del token si es válido, no expirado y no usado."""
    if not token_plano:
        return None
    th = _hash_token(token_plano)
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM password_resets WHERE token_hash = ?",
        (th,),
    ).fetchone()
    if not row:
        return None
    if row["usado_ts"] is not None:
        return None
    if int(time.time()) >= row["expira_ts"]:
        return None
    return TokenInfo(
        usuario_id=row["usuario_id"],
        expira_ts=row["expira_ts"],
        usado=False,
    )


def marcar_usado(token_plano: str) -> bool:
    """Marca el token como usado. Idempotente."""
    th = _hash_token(token_plano)
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "UPDATE password_resets SET usado_ts = ? "
            "WHERE token_hash = ? AND usado_ts IS NULL",
            (int(time.time()), th),
        )
    return cur.rowcount > 0


def limpiar_expirados(antes_de_ts: Optional[int] = None) -> int:
    """Borra tokens expirados o usados hace > 7 días. Devuelve cuántos borró."""
    init_db()
    ahora = int(time.time())
    corte_usados = ahora - 7 * 24 * 3600
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "DELETE FROM password_resets "
            "WHERE expira_ts <= ? OR (usado_ts IS NOT NULL AND usado_ts < ?)",
            (ahora, corte_usados),
        )
    return cur.rowcount


def invalidar_tokens_de_usuario(usuario_id: str) -> int:
    """Marca todos los tokens vigentes de un usuario como usados (rotación)."""
    ahora = int(time.time())
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "UPDATE password_resets SET usado_ts = ? "
            "WHERE usuario_id = ? AND usado_ts IS NULL",
            (ahora, usuario_id),
        )
    return cur.rowcount
