"""
Adapter de envío de email.

Drivers:
  - Resend (preferido): RESEND_API_KEY + MAIL_FROM
  - SMTP genérico (fallback): SMTP_HOST + SMTP_PORT + SMTP_USER + SMTP_PASS
  - Console (último recurso/dev): imprime el email a stdout y devuelve True

Uso:
    from src.mailer import enviar_email
    enviar_email(to="user@x.com", subject="Reset", html="<p>...</p>")
"""
from __future__ import annotations

import os
import json
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional


def _driver_activo() -> str:
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("SMTP_HOST"):
        return "smtp"
    return "console"


def _mail_from() -> str:
    return (
        os.getenv("MAIL_FROM")
        or "JR Verifica EC <noreply@jrautomata.com>"
    )


def _enviar_resend(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Llamada HTTP a Resend (https://resend.com/docs)."""
    import httpx  # ya está en requirements (lo usa bg_client)
    api_key = os.getenv("RESEND_API_KEY", "")
    payload = {
        "from":    _mail_from(),
        "to":      [to],
        "subject": subject,
        "html":    html,
    }
    if text:
        payload["text"] = text
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[mailer.resend] ERROR enviando a {to}: {e}")
        return False


def _enviar_smtp(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    use_ssl = os.getenv("SMTP_SSL", "0") == "1"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = _mail_from()
    msg["To"]      = to
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                if user:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception as e:
        print(f"[mailer.smtp] ERROR enviando a {to}: {e}")
        return False


def _enviar_console(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Modo dev/fallback: imprime el email a stdout (Easypanel logs)."""
    print("=" * 70)
    print("[mailer.CONSOLE] (configura RESEND_API_KEY o SMTP_HOST para envío real)")
    print(f"  To:      {to}")
    print(f"  From:    {_mail_from()}")
    print(f"  Subject: {subject}")
    print("-" * 70)
    print(text or html[:2000])
    print("=" * 70)
    return True


def enviar_email(to: str, subject: str, html: str,
                 text: Optional[str] = None) -> bool:
    """
    Despacha al driver activo. Devuelve True si se envió (o se logueó en
    modo console). NUNCA lanza excepciones — best-effort.
    """
    if not to or "@" not in to:
        return False
    driver = _driver_activo()
    if driver == "resend":
        return _enviar_resend(to, subject, html, text)
    if driver == "smtp":
        return _enviar_smtp(to, subject, html, text)
    return _enviar_console(to, subject, html, text)


def driver_activo_nombre() -> str:
    """Útil para health/debug."""
    return _driver_activo()
