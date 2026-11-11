"""Envío de mails por SMTP con dos cuentas del dominio: ventas y soporte.

Configuración (.env):
  MAIL_SERVER, MAIL_PORT, MAIL_USE_SSL, MAIL_USE_TLS   servidor (compartido)
  MAIL_VENTAS_USERNAME, MAIL_VENTAS_PASSWORD           cuenta ventas@
  MAIL_SOPORTE_USERNAME, MAIL_SOPORTE_PASSWORD         cuenta soporte@
  MAIL_FROM_NAME                                       nombre visible (default "Caricias")

Si falta la cuenta pedida se usa MAIL_USERNAME / MAIL_PASSWORD como respaldo.
"""
import logging
import os
import re
import smtplib
import ssl

from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from flask import current_app

CUENTAS = ("ventas", "soporte")


def _env(name, default=""):
    return (os.getenv(name) or default).strip()


def _credenciales(cuenta):
    if cuenta not in CUENTAS:
        raise ValueError(f"Cuenta de mail desconocida: {cuenta!r}")
    pref = f"MAIL_{cuenta.upper()}_"
    user = _env(pref + "USERNAME") or _env("MAIL_USERNAME")
    password = _env(pref + "PASSWORD") or _env("MAIL_PASSWORD")
    if not user or not password:
        raise RuntimeError(f"Faltan credenciales SMTP para la cuenta '{cuenta}'")
    return user, password


def _html_a_texto(html):
    """Versión texto plano (mejora la entregabilidad y sirve a clientes sin HTML)."""
    texto = re.sub(r"(?is)<(style|head|script)\b.*?</\1>", "", html)
    texto = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", texto)
    texto = re.sub(r"(?i)<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 (\1)", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = re.sub(r"&nbsp;|&zwnj;", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def _construir(to, subject, html, cuenta, cc, bcc, reply_to):
    user, _ = _credenciales(cuenta)
    msg = EmailMessage()
    msg["From"] = formataddr((_env("MAIL_FROM_NAME", "Caricias"), user))
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    msg.set_content(_html_a_texto(html))
    msg.add_alternative(html, subtype="html")
    destinatarios = [to] + list(cc or []) + list(bcc or [])
    return msg, destinatarios


def _enviar_smtp(msg, destinatarios, cuenta):
    user, password = _credenciales(cuenta)
    host = _env("MAIL_SERVER")
    port = int(_env("MAIL_PORT", "465"))
    use_ssl = _env("MAIL_USE_SSL", "true").lower() == "true"
    use_tls = _env("MAIL_USE_TLS", "false").lower() == "true"
    contexto = ssl.create_default_context()

    print(f"[MAIL] conectando a {host}:{port} ssl={use_ssl} tls={use_tls} como {user} → {destinatarios}", flush=True)
    if use_ssl:
        smtp = smtplib.SMTP_SSL(host, port, timeout=10, context=contexto)
    else:
        smtp = smtplib.SMTP(host, port, timeout=10)
    with smtp:
        print("[MAIL] conectado", flush=True)
        if use_tls and not use_ssl:
            smtp.starttls(context=contexto)
        smtp.login(user, password)
        print("[MAIL] login OK", flush=True)
        smtp.send_message(msg, from_addr=user, to_addrs=destinatarios)
        print(f"[MAIL] enviado: {msg['Subject']!r}", flush=True)


def send_email(to: str, subject: str, html: str, cc=None, bcc=None, reply_to=None, cuenta="ventas"):
    """Envía en el momento y lanza la excepción si falla."""
    msg, destinatarios = _construir(to, subject, html, cuenta, cc, bcc, reply_to)
    _enviar_smtp(msg, destinatarios, cuenta)


def send_email_safe(to: str, subject: str, html: str, cc=None, bcc=None, reply_to=None, cuenta="ventas"):
    """Envía dentro de la request y nunca lanza: si falla, queda en el log.

    No se usa un hilo en segundo plano: en el hosting (LiteSpeed) los hilos se
    congelan cuando termina la request y el mail no sale nunca. Cuesta ~1-2 s
    por mail en el checkout/webhook, pero el envío es seguro.
    """
    app = current_app._get_current_object()
    # Por si la app arranca sin logging_setup (ej. local): que se vean los INFO
    if app.logger.level == logging.NOTSET:
        app.logger.setLevel(logging.INFO)
    print(f"[MAIL] preparando: cuenta={cuenta} to={to!r} subject={subject!r}", flush=True)
    try:
        msg, destinatarios = _construir(to, subject, html, cuenta, cc, bcc, reply_to)
        _enviar_smtp(msg, destinatarios, cuenta)
        app.logger.info("EMAIL enviado: cuenta=%s to=%r subject=%r", cuenta, to, subject)
    except Exception:
        app.logger.exception("EMAIL ERROR: cuenta=%s to=%r subject=%r", cuenta, to, subject)
