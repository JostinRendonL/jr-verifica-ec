"""
Módulo de gestión de usuarios para JR Verifica EC.

Schema:
  usuarios(id, email, nombre, password_hash, rol, activo,
           debe_cambiar_pass, creado_por, creado_ts, ultimo_login)

Reglas:
  - email único, case-insensitive (se guarda en minúsculas)
  - password mínimo 8 caracteres
  - rol ∈ {'admin', 'operador'}
  - soft delete (activo=0), nunca DELETE real
  - bootstrap: crear admin desde ADMIN_EMAIL + APP_PASSWORD si no existe ninguno
  - usuarios creados por admin → debe_cambiar_pass=1 (forzado en primer login)
"""
from __future__ import annotations

import os
import time
import uuid
import threading
import sqlite3
from pathlib import Path
from typing import Optional, NamedTuple

import bcrypt


# ── Config ──────────────────────────────────────────────────────────────────
_DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_FILE = _DATA_DIR / "historial.db"   # MISMA DB que historial (multi-tabla)

_write_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

MIN_PASSWORD_LEN = 8
ROLES_VALIDOS = {"admin", "operador"}

DEFAULT_ADMIN_EMAIL = "admin@jrautomata.com"


# ── Modelo ──────────────────────────────────────────────────────────────────
class Usuario(NamedTuple):
    id: str
    email: str
    nombre: str
    rol: str
    activo: bool
    debe_cambiar_pass: bool
    creado_por: Optional[str]
    creado_ts: int
    ultimo_login: Optional[int]


# ── Schema ──────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id                  TEXT PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    nombre              TEXT NOT NULL,
    password_hash       TEXT NOT NULL,
    rol                 TEXT NOT NULL DEFAULT 'operador',
    activo              INTEGER NOT NULL DEFAULT 1,
    debe_cambiar_pass   INTEGER NOT NULL DEFAULT 0,
    creado_por          TEXT REFERENCES usuarios(id) ON DELETE SET NULL,
    creado_ts           INTEGER NOT NULL,
    ultimo_login        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email);
CREATE INDEX IF NOT EXISTS idx_usuarios_rol   ON usuarios(rol);
"""


def _get_conn() -> sqlite3.Connection:
    """Singleton conexión a la misma DB que historial."""
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
    _conn.execute("PRAGMA foreign_keys=ON")     # crítico: FK realmente activas
    _conn.executescript(_SCHEMA)
    return _conn


def init_db() -> None:
    """Forzar creación de tablas. Llamable en startup."""
    _get_conn()


def _migrar_historial_si_falta_columna() -> None:
    """
    Idempotente: agrega columna `usuario_id` a la tabla `historial` si
    todavía no existe. Las filas viejas quedan con NULL (= 'pre-multi-user').
    """
    conn = _get_conn()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(historial)")}
    if "usuario_id" not in cols:
        # No usamos REFERENCES en ALTER (sqlite no soporta FK retroactiva via ALTER).
        # La integridad se mantiene por convención en el código de inserción.
        conn.execute("ALTER TABLE historial ADD COLUMN usuario_id TEXT")
        print("[usuarios] columna historial.usuario_id agregada")


# ── Helpers internos ────────────────────────────────────────────────────────
def _normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verificar_password(password: str, hash_str: str) -> bool:
    if not password or not hash_str:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_str.encode("utf-8"))
    except Exception:
        return False


def _row_a_usuario(row: sqlite3.Row) -> Usuario:
    return Usuario(
        id=row["id"],
        email=row["email"],
        nombre=row["nombre"],
        rol=row["rol"],
        activo=bool(row["activo"]),
        debe_cambiar_pass=bool(row["debe_cambiar_pass"]),
        creado_por=row["creado_por"],
        creado_ts=row["creado_ts"],
        ultimo_login=row["ultimo_login"],
    )


# ── Excepciones ─────────────────────────────────────────────────────────────
class UsuarioError(Exception):
    """Error de validación o regla de negocio."""


# ── API pública ─────────────────────────────────────────────────────────────
def crear_usuario(
    email: str,
    nombre: str,
    password: str,
    rol: str = "operador",
    creado_por: Optional[str] = None,
    debe_cambiar_pass: bool = False,
) -> Usuario:
    """Crea un usuario. Lanza UsuarioError en validación o duplicado."""
    email = _normalizar_email(email)
    nombre = (nombre or "").strip()

    if not email or "@" not in email:
        raise UsuarioError("Email inválido")
    if not nombre or len(nombre) < 2:
        raise UsuarioError("Nombre requerido (≥2 caracteres)")
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise UsuarioError(f"Password mínimo {MIN_PASSWORD_LEN} caracteres")
    if rol not in ROLES_VALIDOS:
        raise UsuarioError(f"Rol inválido: {rol}")

    conn = _get_conn()
    user_id = uuid.uuid4().hex
    ts = int(time.time())
    pwd_hash = _hash_password(password)

    with _write_lock:
        try:
            conn.execute(
                """INSERT INTO usuarios
                   (id, email, nombre, password_hash, rol, activo,
                    debe_cambiar_pass, creado_por, creado_ts)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (user_id, email, nombre, pwd_hash, rol,
                 1 if debe_cambiar_pass else 0, creado_por, ts),
            )
        except sqlite3.IntegrityError as e:
            raise UsuarioError(f"Email ya registrado: {email}") from e

    return obtener_por_id(user_id)  # type: ignore[return-value]


def autenticar(email: str, password: str) -> Optional[Usuario]:
    """Devuelve el Usuario si email+password match y el usuario está activo."""
    email = _normalizar_email(email)
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM usuarios WHERE email = ? AND activo = 1",
        (email,),
    ).fetchone()
    if not row:
        return None
    if not _verificar_password(password, row["password_hash"]):
        return None

    # Marcar último login (best-effort, no bloquea el flow)
    try:
        with _write_lock:
            conn.execute(
                "UPDATE usuarios SET ultimo_login = ? WHERE id = ?",
                (int(time.time()), row["id"]),
            )
    except Exception:
        pass

    # Re-fetch para devolver el ultimo_login fresco
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (row["id"],)).fetchone()
    return _row_a_usuario(row)


def obtener_por_id(user_id: str) -> Optional[Usuario]:
    if not user_id:
        return None
    conn = _get_conn()
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    return _row_a_usuario(row) if row else None


def obtener_por_email(email: str) -> Optional[Usuario]:
    email = _normalizar_email(email)
    conn = _get_conn()
    row = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
    return _row_a_usuario(row) if row else None


def listar(solo_activos: bool = True) -> list[Usuario]:
    conn = _get_conn()
    if solo_activos:
        rows = conn.execute(
            "SELECT * FROM usuarios WHERE activo = 1 ORDER BY creado_ts ASC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM usuarios ORDER BY creado_ts ASC"
        ).fetchall()
    return [_row_a_usuario(r) for r in rows]


def existe_admin(activo: bool = True) -> bool:
    """¿Hay al menos un admin (activo)?"""
    conn = _get_conn()
    q = "SELECT 1 FROM usuarios WHERE rol = 'admin'"
    if activo:
        q += " AND activo = 1"
    return conn.execute(q + " LIMIT 1").fetchone() is not None


def desactivar(user_id: str, ejecutor_id: Optional[str] = None) -> bool:
    """
    Soft delete. Bloquea desactivar al último admin activo.
    `ejecutor_id` se usa solo para evitar auto-desactivación.
    """
    u = obtener_por_id(user_id)
    if not u or not u.activo:
        return False
    if ejecutor_id and ejecutor_id == user_id:
        raise UsuarioError("No puedes desactivar tu propia cuenta")
    if u.rol == "admin":
        # Contar admins activos restantes
        conn = _get_conn()
        n_admins = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1"
        ).fetchone()[0]
        if n_admins <= 1:
            raise UsuarioError("No se puede desactivar al último admin activo")

    conn = _get_conn()
    with _write_lock:
        conn.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (user_id,))
    return True


def reactivar(user_id: str) -> bool:
    u = obtener_por_id(user_id)
    if not u or u.activo:
        return False
    conn = _get_conn()
    with _write_lock:
        conn.execute("UPDATE usuarios SET activo = 1 WHERE id = ?", (user_id,))
    return True


def cambiar_password(user_id: str, nueva_password: str) -> bool:
    """Cambia la password. Limpia el flag debe_cambiar_pass."""
    if not nueva_password or len(nueva_password) < MIN_PASSWORD_LEN:
        raise UsuarioError(f"Password mínimo {MIN_PASSWORD_LEN} caracteres")
    u = obtener_por_id(user_id)
    if not u:
        return False
    nuevo_hash = _hash_password(nueva_password)
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "UPDATE usuarios SET password_hash = ?, debe_cambiar_pass = 0 WHERE id = ?",
            (nuevo_hash, user_id),
        )
    return True


def cambiar_rol(user_id: str, nuevo_rol: str) -> bool:
    if nuevo_rol not in ROLES_VALIDOS:
        raise UsuarioError(f"Rol inválido: {nuevo_rol}")
    u = obtener_por_id(user_id)
    if not u:
        return False
    # No degradar al último admin
    if u.rol == "admin" and nuevo_rol != "admin":
        conn = _get_conn()
        n = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1"
        ).fetchone()[0]
        if n <= 1:
            raise UsuarioError("No se puede degradar al último admin activo")
    conn = _get_conn()
    with _write_lock:
        conn.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (nuevo_rol, user_id))
    return True


# ── Bootstrap ───────────────────────────────────────────────────────────────
def bootstrap_admin_si_falta() -> Optional[Usuario]:
    """
    Si no hay ningún admin activo, crea uno desde ADMIN_EMAIL + APP_PASSWORD.
    Idempotente: no hace nada si ya existe al menos un admin activo.
    El bootstrap admin NO requiere cambiar pass (ya la conoce el operador).
    """
    init_db()
    _migrar_historial_si_falta_columna()

    if existe_admin(activo=True):
        return None

    app_password = os.getenv("APP_PASSWORD", "").strip()
    if not app_password or app_password == "cambiar":
        print("[usuarios.bootstrap] no hay admin y APP_PASSWORD no es válido — saltando")
        return None
    if len(app_password) < MIN_PASSWORD_LEN:
        print(f"[usuarios.bootstrap] APP_PASSWORD < {MIN_PASSWORD_LEN} chars — saltando")
        return None

    admin_email = _normalizar_email(os.getenv("ADMIN_EMAIL", "") or DEFAULT_ADMIN_EMAIL)
    admin_nombre = (os.getenv("ADMIN_NOMBRE", "") or "Administrador").strip()

    # Si el email ya existe (ej. desactivado) → reactivarlo y promover a admin
    existente = obtener_por_email(admin_email)
    if existente:
        conn = _get_conn()
        with _write_lock:
            conn.execute(
                "UPDATE usuarios SET activo = 1, rol = 'admin' WHERE id = ?",
                (existente.id,),
            )
        cambiar_password(existente.id, app_password)
        print(f"[usuarios.bootstrap] admin existente {admin_email} reactivado")
        return obtener_por_id(existente.id)

    u = crear_usuario(
        email=admin_email,
        nombre=admin_nombre,
        password=app_password,
        rol="admin",
        creado_por=None,
        debe_cambiar_pass=False,
    )
    print(f"[usuarios.bootstrap] ✅ admin creado: {admin_email}")
    return u
