"""Autenticación con bcrypt + cookie firmada + rate limiting básico."""
import os
import time
import secrets
import bcrypt
from itsdangerous import URLSafeSerializer, BadSignature

APP_PASSWORD      = os.getenv("APP_PASSWORD", "cambiar")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH", "")  # opcional: hash bcrypt pre-generado
SESSION_SECRET    = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32)
COOKIE_NAME       = "jr_session"
SESSION_MAX_AGE   = 60 * 60 * 24  # 24h

# Rate limit
_RATE_LIMIT_MAX_INTENTOS  = 5
_RATE_LIMIT_VENTANA_SEG   = 600   # 10 min
_intentos_fallidos: dict[str, list[float]] = {}

_serializer = URLSafeSerializer(SESSION_SECRET, salt="jr-verifica")

# Generar hash al inicio si solo nos dieron password plano (lazy)
_hash_cacheado: bytes | None = None


def _obtener_hash() -> bytes | None:
    """Devuelve el hash bcrypt a usar para validar."""
    global _hash_cacheado
    if _hash_cacheado is not None:
        return _hash_cacheado

    if APP_PASSWORD_HASH:
        _hash_cacheado = APP_PASSWORD_HASH.encode("utf-8")
        return _hash_cacheado

    if APP_PASSWORD and APP_PASSWORD != "cambiar":
        # Hashear en memoria (cada restart genera salt nuevo, pero hash es válido)
        _hash_cacheado = bcrypt.hashpw(APP_PASSWORD.encode("utf-8"), bcrypt.gensalt())
        return _hash_cacheado

    return None


def password_correcta(password: str) -> bool:
    """Verifica con bcrypt (constant-time)."""
    if not password:
        return False
    h = _obtener_hash()
    if not h:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), h)
    except Exception:
        return False


# ── Rate limiting ─────────────────────────────────────────────────────────────

def _limpiar_intentos_viejos(ip: str, ahora: float) -> None:
    """Quita intentos fuera de la ventana de tiempo."""
    if ip not in _intentos_fallidos:
        return
    _intentos_fallidos[ip] = [
        t for t in _intentos_fallidos[ip]
        if ahora - t < _RATE_LIMIT_VENTANA_SEG
    ]
    if not _intentos_fallidos[ip]:
        del _intentos_fallidos[ip]


def ip_bloqueada(ip: str) -> tuple[bool, int]:
    """Retorna (bloqueada, segundos_restantes_aprox)."""
    ahora = time.time()
    _limpiar_intentos_viejos(ip, ahora)

    intentos = _intentos_fallidos.get(ip, [])
    if len(intentos) >= _RATE_LIMIT_MAX_INTENTOS:
        primer_intento = intentos[0]
        seg_restantes = int(_RATE_LIMIT_VENTANA_SEG - (ahora - primer_intento))
        return True, max(seg_restantes, 0)
    return False, 0


def registrar_intento_fallido(ip: str) -> None:
    _intentos_fallidos.setdefault(ip, []).append(time.time())


def limpiar_intentos(ip: str) -> None:
    """Al login exitoso, limpiamos los intentos del IP."""
    _intentos_fallidos.pop(ip, None)


# ── Cookie ─────────────────────────────────────────────────────────────────────

def crear_cookie() -> str:
    return _serializer.dumps({"auth": True, "ts": int(time.time())})


def cookie_valida(cookie_value: str | None) -> bool:
    if not cookie_value:
        return False
    try:
        data = _serializer.loads(cookie_value)
        if data.get("auth") is not True:
            return False
        ts = data.get("ts", 0)
        # Validar que la cookie no haya expirado (defensa en profundidad además del max_age)
        if time.time() - ts > SESSION_MAX_AGE:
            return False
        return True
    except BadSignature:
        return False


# ── Validación de cédula ecuatoriana ──────────────────────────────────────────

def cedula_valida_ec(cedula: str) -> bool:
    """
    Valida cédula ecuatoriana usando el algoritmo del dígito verificador.
    Solo retorna True si pasa el check oficial del Registro Civil.
    """
    if not cedula or len(cedula) != 10 or not cedula.isdigit():
        return False

    provincia = int(cedula[:2])
    if not (1 <= provincia <= 24) and provincia != 30:
        return False

    tercer_digito = int(cedula[2])
    if tercer_digito >= 6:
        return False

    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for i, c in enumerate(cedula[:9]):
        producto = int(c) * coeficientes[i]
        if producto >= 10:
            producto -= 9
        suma += producto

    digito_verificador = (10 - (suma % 10)) % 10
    return digito_verificador == int(cedula[9])
