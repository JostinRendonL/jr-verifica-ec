"""Autenticación simple con contraseña global + cookie firmada."""
import os
import secrets
from itsdangerous import URLSafeSerializer, BadSignature

APP_PASSWORD   = os.getenv("APP_PASSWORD", "cambiar")
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32)
COOKIE_NAME    = "jr_session"

_serializer = URLSafeSerializer(SESSION_SECRET, salt="jr-verifica")


def password_correcta(password: str) -> bool:
    return password == APP_PASSWORD and password != "cambiar"


def crear_cookie() -> str:
    """Genera el valor firmado a guardar en la cookie."""
    return _serializer.dumps({"auth": True})


def cookie_valida(cookie_value: str | None) -> bool:
    if not cookie_value:
        return False
    try:
        data = _serializer.loads(cookie_value)
        return data.get("auth") is True
    except BadSignature:
        return False
