# services/notifications.py
import os
from flask import current_app
from models import Usuario, Pedido, Pago
from services.email_service import send_email


# ─────────────────────────────────────────────
#  Helpers internos
# ─────────────────────────────────────────────

def _admin_email():
    return current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL")


def _frontend_url():
    return os.getenv("FRONTEND_URL", "#").rstrip("/")


def _safe_send(to, subject, html):
    if not to:
        print("EMAIL: destinatario vacío, se ignora:", subject)
        return
    try:
        send_email(to=to, subject=subject, html=html)
    except Exception as e:
        print("EMAIL ERROR:", subject, repr(e))


# ─────────────────────────────────────────────
#  Template base — Paleta Caricias (lavanda/lila sobre blanco)
# ─────────────────────────────────────────────

def _base_template(content: str, preview_text: str = "") -> str:
    """
    Envuelve el contenido en el layout general de Caricias.
    Estética del front: fondo claro, acentos lavanda, tipografías modernas,
    inspirado en la pluma lila del logo.
    Usa tablas para compatibilidad máxima con clientes de correo.
    """
    frontend = _frontend_url()
    logo_url = f"{frontend}/caricias-logo.png" if frontend != "#" else ""
    feather_url = f"{frontend}/caricias-logo-pluma.png" if frontend != "#" else ""

    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Caricias</title>
  <!--[if mso]>
  <noscript>
    <xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml>
  </noscript>
  <![endif]-->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=DM+Sans:wght@400;500;600&display=swap');

    body, table, td, a {{
      -webkit-text-size-adjust: 100%;
      -ms-text-size-adjust: 100%;
    }}
    body {{
      margin: 0;
      padding: 0;
      background-color: #f6eef3;
      font-family: 'DM Sans', Arial, sans-serif;
    }}
    table {{ border-collapse: collapse; }}
    img {{ border: 0; display: block; }}
    a {{ color: inherit; text-decoration: none; }}

    .email-wrapper {{
      background-color: #f6eef3;
      background-image: linear-gradient(180deg, #f6eef3 0%, #ffffff 220px);
      padding: 40px 16px;
    }}
    .email-container {{
      max-width: 580px;
      margin: 0 auto;
      background-color: #ffffff;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #e8d6e4;
      box-shadow: 0 8px 24px rgba(176, 120, 170, 0.10);
    }}

    /* Header */
    .email-header {{
      background-color: #ffffff;
      padding: 32px 40px 24px;
      border-bottom: 1px solid #f1e2ec;
      text-align: center;
    }}
    .brand-logo {{
      width: 56px;
      height: auto;
      margin: 0 auto 12px;
    }}
    .brand-name {{
      font-family: 'Space Grotesk', Georgia, serif;
      font-size: 28px;
      font-weight: 600;
      letter-spacing: 2px;
      color: #2a212a;
      margin: 0;
    }}
    .brand-tagline {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 11px;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: #b07aa8;
      margin-top: 6px;
    }}

    /* Body */
    .email-body {{
      padding: 36px 40px 28px;
    }}
    .greeting {{
      font-family: 'Space Grotesk', Georgia, serif;
      font-size: 24px;
      font-weight: 600;
      color: #2a212a;
      margin: 0 0 20px;
      line-height: 1.3;
    }}
    .body-text {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 15px;
      line-height: 1.7;
      color: #5a4a58;
      margin: 0 0 16px;
    }}

    /* Status badge — pill estilo botón outline del front */
    .status-badge {{
      display: inline-block;
      background-color: #f6eaf2;
      border: 1px solid #e3c8dc;
      color: #b07aa8;
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 5px 14px;
      border-radius: 999px;
      margin-bottom: 18px;
    }}

    /* Info card — replica las cards del front con border y radius suaves */
    .info-card {{
      background-color: #fbf6f9;
      border: 1px solid #ecdaea;
      border-left: 3px solid #c084bc;
      border-radius: 10px;
      padding: 20px 24px;
      margin: 24px 0;
    }}
    .info-label {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 11px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: #8a6f86;
    }}
    .info-value {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 14px;
      font-weight: 500;
      color: #2a212a;
      text-align: right;
    }}
    .info-value.highlight {{
      color: #b07aa8;
      font-weight: 600;
    }}

    /* CTA button — estilo botón primario del front */
    .cta-wrapper {{
      text-align: center;
      margin: 32px 0 12px;
    }}
    .cta-button {{
      display: inline-block;
      background-color: #c084bc;
      color: #ffffff !important;
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      padding: 14px 32px;
      border-radius: 10px;
      text-decoration: none;
      box-shadow: 0 4px 14px rgba(192, 132, 188, 0.35);
    }}
    .cta-button.secondary {{
      background-color: #ffffff;
      color: #b07aa8 !important;
      border: 1px solid #e3c8dc;
      box-shadow: none;
    }}

    /* Alert box (error / pago rechazado) */
    .alert-box {{
      background-color: #fdf2f2;
      border: 1px solid #f5d0d0;
      border-left: 3px solid #c0392b;
      border-radius: 10px;
      padding: 16px 20px;
      margin: 20px 0;
    }}
    .alert-box .body-text {{
      color: #a3382b;
      margin: 0;
    }}

    /* Success box */
    .success-box {{
      background-color: #f0faf3;
      border: 1px solid #c8ebd2;
      border-left: 3px solid #2e9d5b;
      border-radius: 10px;
      padding: 16px 20px;
      margin: 20px 0;
    }}
    .success-box .body-text {{
      color: #1f7a45;
      margin: 0;
    }}

    /* Bank data */
    .bank-block {{
      background-color: #ffffff;
      border: 1px solid #ecdaea;
      border-radius: 10px;
      padding: 4px 24px;
      margin: 20px 0;
    }}
    .bank-field {{
      padding: 14px 0;
      border-bottom: 1px solid #f4e5ee;
    }}
    .bank-field:last-child {{ border-bottom: none; }}
    .bank-label {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 10px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: #8a6f86;
      margin-bottom: 4px;
    }}
    .bank-value {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 16px;
      font-weight: 600;
      color: #2a212a;
      letter-spacing: 0.5px;
    }}

    /* Divider */
    .divider {{
      border: none;
      border-top: 1px solid #f1e2ec;
      margin: 24px 0;
    }}

    /* Footer */
    .email-footer {{
      background-color: #fbf6f9;
      border-top: 1px solid #f1e2ec;
      padding: 24px 40px;
      text-align: center;
    }}
    .footer-text {{
      font-family: 'DM Sans', Arial, sans-serif;
      font-size: 12px;
      color: #8a6f86;
      line-height: 1.6;
      margin: 0 0 6px;
    }}
    .footer-link {{
      color: #b07aa8 !important;
      text-decoration: underline;
    }}
    .footer-brand {{
      font-family: 'Space Grotesk', Georgia, serif;
      font-size: 14px;
      font-weight: 600;
      color: #2a212a;
      letter-spacing: 1px;
      margin-bottom: 4px;
    }}

    @media only screen and (max-width: 480px) {{
      .email-body {{ padding: 26px 22px 22px; }}
      .email-header {{ padding: 26px 22px 20px; }}
      .email-footer {{ padding: 20px 22px; }}
      .brand-name {{ font-size: 24px; }}
      .greeting {{ font-size: 21px; }}
    }}
  </style>
</head>
<body>
  <!-- Preview text (hidden) -->
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
    {preview_text}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
  </div>

  <div class="email-wrapper">
    <div class="email-container">

      <!-- HEADER -->
      <div class="email-header">
        {f'<img src="{feather_url}" alt="Caricias" class="brand-logo" width="56" />' if feather_url else ''}
        <h1 class="brand-name">Caricias</h1>
        <div class="brand-tagline">Bienestar íntimo</div>
      </div>

      <!-- BODY -->
      <div class="email-body">
        {content}
      </div>

      <!-- FOOTER -->
      <div class="email-footer">
        <div class="footer-brand">Caricias</div>
        <p class="footer-text">
          Recibís este correo porque tenés una cuenta en Caricias.<br/>
          Si no reconocés esta actividad, <a href="{frontend}/contacto" class="footer-link">contactanos</a>.
        </p>
        <p class="footer-text" style="margin-top:12px;">
          © 2026 Caricias · Todos los derechos reservados
        </p>
      </div>

    </div>
  </div>
</body>
</html>
"""


# ─────────────────────────────────────────────
#  Notificaciones al usuario
# ─────────────────────────────────────────────

def send_user_welcome(usuario: Usuario):
    nombre = usuario.nombre or "allí"
    frontend = _frontend_url()
    content = f"""
      <span class="status-badge">Cuenta creada</span>
      <h1 class="greeting">Bienvenida/o,<br/>{nombre}.</h1>
      <p class="body-text">
        Tu cuenta en <strong style="color:#2a212a;">Caricias</strong> fue creada exitosamente
        con el email <strong style="color:#2a212a;">{usuario.email}</strong>.
      </p>
      <p class="body-text">
        Desde tu perfil podés explorar nuestro catálogo, realizar compras y hacer
        seguimiento de tus pedidos con total discreción.
      </p>
      <div class="success-box">
        <p class="body-text">
          Tu información está protegida y tu privacidad, garantizada.
        </p>
      </div>
      <div class="cta-wrapper">
        <a href="{frontend}/catalogo" class="cta-button">
          Explorar catálogo
        </a>
      </div>
    """
    _safe_send(
        usuario.email,
        "Bienvenida/o a Caricias",
        _base_template(content, preview_text=f"Hola {nombre}, tu cuenta está lista.")
    )


def send_user_order_created(usuario: Usuario, pedido: Pedido):
    nombre = usuario.nombre or "allí"
    frontend = _frontend_url()
    content = f"""
      <span class="status-badge">Pedido recibido</span>
      <h1 class="greeting">Tu pedido está<br/>en camino, {nombre}.</h1>
      <p class="body-text">
        Recibimos tu pedido y ya lo estamos procesando.
        Te notificaremos ante cada cambio de estado.
      </p>
      <div class="info-card">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td class="info-label">Número de pedido</td>
            <td class="info-value highlight">#{pedido.id}</td>
          </tr>
          <tr>
            <td class="info-label" style="padding-top:12px;">Estado</td>
            <td class="info-value" style="padding-top:12px;">{pedido.estado}</td>
          </tr>
          <tr>
            <td class="info-label" style="padding-top:12px;">Total</td>
            <td class="info-value" style="padding-top:12px;">${pedido.total:.2f}</td>
          </tr>
        </table>
      </div>
      <p class="body-text" style="font-size:13px;color:#8a6f86;">
        El envío se realiza en embalaje neutro y discreto, sin identificación del remitente.
      </p>
      <div class="cta-wrapper">
        <a href="{frontend}/mis-pedidos/{pedido.id}" class="cta-button">
          Ver mi pedido
        </a>
      </div>
    """
    _safe_send(
        usuario.email,
        f"Pedido #{pedido.id} confirmado",
        _base_template(content, preview_text=f"Pedido #{pedido.id} recibido · ${pedido.total:.2f}")
    )


def send_user_payment_approved(usuario: Usuario, pedido: Pedido, pago: Pago):
    nombre = usuario.nombre or "allí"
    frontend = _frontend_url()
    content = f"""
      <span class="status-badge">Pago aprobado</span>
      <h1 class="greeting">¡Pago confirmado,<br/>{nombre}!</h1>
      <p class="body-text">
        Tu pago fue procesado exitosamente. Ya estamos preparando tu pedido
        para que llegue a vos lo antes posible.
      </p>
      <div class="info-card">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td class="info-label">Pedido</td>
            <td class="info-value highlight">#{pedido.id}</td>
          </tr>
          <tr>
            <td class="info-label" style="padding-top:12px;">Monto abonado</td>
            <td class="info-value" style="padding-top:12px;">${pago.monto:.2f}</td>
          </tr>
          <tr>
            <td class="info-label" style="padding-top:12px;">Método</td>
            <td class="info-value" style="padding-top:12px;">{pago.metodo_pago}</td>
          </tr>
        </table>
      </div>
      <p class="body-text">
        Te avisaremos cuando tu pedido sea despachado con el número de seguimiento.
      </p>
      <div class="cta-wrapper">
        <a href="{frontend}/mis-pedidos/{pedido.id}" class="cta-button">
          Seguir mi pedido
        </a>
      </div>
    """
    _safe_send(
        usuario.email,
        f"Pago aprobado · Pedido #{pedido.id}",
        _base_template(content, preview_text=f"Tu pago de ${pago.monto:.2f} fue confirmado.")
    )


def send_user_payment_rejected(usuario: Usuario, pedido: Pedido, pago: Pago):
    nombre = usuario.nombre or "allí"
    detail = pago.detalle_estado or "Sin detalle disponible"
    frontend = _frontend_url()
    content = f"""
      <span class="status-badge" style="background:#fdf2f2;border-color:#f5d0d0;color:#c0392b;">Pago rechazado</span>
      <h1 class="greeting">Hubo un problema<br/>con tu pago.</h1>
      <p class="body-text">
        Lamentablemente el pago del pedido <strong style="color:#2a212a;">#{pedido.id}</strong>
        no pudo procesarse. Tu pedido sigue reservado y podés reintentar el pago.
      </p>
      <div class="alert-box">
        <p class="body-text">Motivo: <strong>{detail}</strong></p>
      </div>
      <p class="body-text">
        Podés intentar con otra tarjeta, cambiar el método de pago o contactarnos
        si el problema persiste.
      </p>
      <div class="cta-wrapper">
        <a href="{frontend}/mis-pedidos/{pedido.id}/pagar" class="cta-button">
          Reintentar pago
        </a>
      </div>
    """
    _safe_send(
        usuario.email,
        f"Problema con tu pago · Pedido #{pedido.id}",
        _base_template(content, preview_text="Tu pago no pudo procesarse. Podés reintentarlo.")
    )


def send_user_transfer_instructions(usuario: Usuario, pedido: Pedido, pago: Pago, instrucciones: dict):
    nombre = usuario.nombre or "allí"
    frontend = _frontend_url()
    content = f"""
      <span class="status-badge">Transferencia bancaria</span>
      <h1 class="greeting">Instrucciones de<br/>pago, {nombre}.</h1>
      <p class="body-text">
        Para confirmar tu pedido <strong style="color:#2a212a;">#{pedido.id}</strong>,
        realizá la transferencia por el monto indicado a los datos bancarios a continuación.
      </p>

      <div class="info-card">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td class="info-label">Monto a transferir</td>
            <td class="info-value highlight">${pago.monto:.2f}</td>
          </tr>
          <tr>
            <td class="info-label" style="padding-top:12px;">Concepto / Referencia</td>
            <td class="info-value" style="padding-top:12px;color:#b07aa8;">
              {instrucciones.get("concepto", f"Pedido-{pedido.id}")}
            </td>
          </tr>
        </table>
      </div>

      <p class="body-text" style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#8a6f86;margin-bottom:8px;">
        Datos bancarios
      </p>
      <div class="bank-block">
        <div class="bank-field">
          <div class="bank-label">Alias</div>
          <div class="bank-value">{instrucciones.get("alias", "—")}</div>
        </div>
        <div class="bank-field">
          <div class="bank-label">CBU</div>
          <div class="bank-value" style="font-size:14px;letter-spacing:1.5px;">{instrucciones.get("cbu", "—")}</div>
        </div>
        <div class="bank-field">
          <div class="bank-label">Titular</div>
          <div class="bank-value">{instrucciones.get("titular", "—")}</div>
        </div>
      </div>

      <p class="body-text" style="font-size:13px;">
        Una vez realizada la transferencia, marcala como <strong style="color:#2a212a;">"enviada"</strong>
        desde tu perfil o adjuntá el comprobante para que podamos verificarla.
      </p>
      <div class="cta-wrapper">
        <a href="{frontend}/mis-pedidos/{pedido.id}/comprobante" class="cta-button">
          Subir comprobante
        </a>
      </div>
    """
    _safe_send(
        usuario.email,
        f"Instrucciones de transferencia · Pedido #{pedido.id}",
        _base_template(content, preview_text=f"Transferí ${pago.monto:.2f} para confirmar tu pedido #{pedido.id}.")
    )


def send_user_transfer_sent(usuario: Usuario, pedido: Pedido):
    nombre = usuario.nombre or "allí"
    frontend = _frontend_url()
    content = f"""
      <span class="status-badge">Transferencia informada</span>
      <h1 class="greeting">Recibimos tu aviso,<br/>{nombre}.</h1>
      <p class="body-text">
        Registramos que informaste la transferencia del pedido
        <strong style="color:#2a212a;">#{pedido.id}</strong>.
      </p>
      <div class="success-box">
        <p class="body-text">
          Nuestro equipo verificará el pago y recibirás una notificación
          cuando tu pedido pase a preparación.
        </p>
      </div>
      <p class="body-text">
        El proceso de verificación suele demorar entre <strong style="color:#2a212a;">1 y 2 horas hábiles</strong>.
      </p>
      <div class="cta-wrapper">
        <a href="{frontend}/mis-pedidos/{pedido.id}" class="cta-button">
          Ver estado del pedido
        </a>
      </div>
    """
    _safe_send(
        usuario.email,
        f"Transferencia informada · Pedido #{pedido.id}",
        _base_template(content, preview_text="Recibimos tu aviso. Verificaremos el pago a la brevedad.")
    )


# ─────────────────────────────────────────────
#  Notificaciones al admin (funcionales, en tono Caricias)
# ─────────────────────────────────────────────

def _admin_html(title: str, rows: list[tuple]) -> str:
    rows_html = "".join(
        f"<tr>"
        f"<td style='padding:8px 14px;color:#8a6f86;font-size:12px;letter-spacing:1px;"
        f"text-transform:uppercase;border-bottom:1px solid #f4e5ee;'>{k}</td>"
        f"<td style='padding:8px 14px;color:#2a212a;font-size:14px;font-weight:600;"
        f"border-bottom:1px solid #f4e5ee;'>{v}</td>"
        f"</tr>"
        for k, v in rows
    )
    return f"""
    <div style="background:#ffffff;font-family:'DM Sans',Arial,sans-serif;padding:24px;
                border:1px solid #e8d6e4;border-radius:12px;color:#2a212a;max-width:580px;margin:24px auto;">
      <p style="font-family:'Space Grotesk',Georgia,serif;font-size:16px;margin:0 0 16px;
                color:#b07aa8;font-weight:600;letter-spacing:0.5px;">{title}</p>
      <table style="border-collapse:collapse;width:100%;background:#fbf6f9;border-radius:8px;overflow:hidden;">
        {rows_html}
      </table>
    </div>
    """


def send_admin_new_order(pedido: Pedido, usuario: Usuario | None):
    u = usuario.email if usuario else "desconocido"
    html = _admin_html(f"Nuevo pedido #{pedido.id}", [
        ("Usuario", u),
        ("Total", f"${pedido.total:.2f}"),
        ("Estado", pedido.estado),
    ])
    _safe_send(_admin_email(), f"[Caricias] Nuevo pedido #{pedido.id}", html)


def send_admin_payment_approved(pedido: Pedido, pago: Pago, usuario: Usuario | None):
    u = usuario.email if usuario else "desconocido"
    html = _admin_html(f"Pago aprobado · Pedido #{pedido.id}", [
        ("Usuario", u),
        ("Monto", f"${pago.monto:.2f}"),
        ("Método", pago.metodo_pago),
    ])
    _safe_send(_admin_email(), f"[Caricias] Pago aprobado · Pedido #{pedido.id}", html)


def send_admin_payment_rejected(pedido: Pedido, pago: Pago, usuario: Usuario | None):
    u = usuario.email if usuario else "desconocido"
    html = _admin_html(f"Pago rechazado · Pedido #{pedido.id}", [
        ("Usuario", u),
        ("Monto", f"${pago.monto:.2f}"),
        ("Método", pago.metodo_pago),
    ])
    _safe_send(_admin_email(), f"[Caricias] Pago rechazado · Pedido #{pedido.id}", html)


def send_admin_transfer_sent(pedido: Pedido, usuario: Usuario | None):
    u = usuario.email if usuario else "desconocido"
    html = _admin_html(f"Transferencia informada · Pedido #{pedido.id}", [
        ("Usuario", u),
        ("Acción requerida", "Verificar comprobante / acreditación"),
    ])
    _safe_send(_admin_email(), f"[Caricias] Transferencia a verificar · Pedido #{pedido.id}", html)
