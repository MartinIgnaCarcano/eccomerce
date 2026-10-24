# services/notifications.py
#
# Mails transaccionales. Remitentes:
#   ventas@  → pedidos, pagos, transferencias y avisos al admin
#   soporte@ → bienvenida
# Los datos que vienen del usuario (nombre, email, teléfono, nombres de
# producto) se escapan siempre con _e() antes de meterlos en el HTML.
import os
from datetime import datetime
from flask import current_app
from markupsafe import escape
from models import Usuario, Pedido, Pago
from services.email_service import send_email_async


# ─────────────────────────────────────────────
#  Helpers internos
# ─────────────────────────────────────────────

ESTADOS_PEDIDO = {
    "PENDIENTE_PAGO": "Pendiente de pago",
    "PAGADO": "Pagado",
    "RECHAZADO": "Pago rechazado",
    "EXPIRADO": "Vencido",
    "REVISAR": "En revisión",
    "ENVIADO": "Enviado",
    "ENTREGADO": "Entregado",
}

METODOS_PAGO = {
    "mercadopago": "Mercado Pago",
    "debito": "Tarjeta de débito",
    "credito": "Tarjeta de crédito (+10%)",
    "transferencia": "Transferencia bancaria",
}


def _e(valor) -> str:
    return str(escape("" if valor is None else valor))


def _admin_email():
    return current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL")


def _frontend_url():
    return (os.getenv("FRONTEND_URL") or "https://cariciassexshop.com").strip().rstrip("/")


def _money(valor) -> str:
    """$ 12.345,67 (formato argentino)."""
    s = f"{float(valor or 0):,.2f}"
    return "$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fecha(dt: datetime | None) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def _nombre(usuario: Usuario | None) -> str:
    return _e((usuario.nombre if usuario else None) or "allí")


def _metodo(pago: Pago) -> str:
    return _e(METODOS_PAGO.get(pago.metodo_pago, pago.metodo_pago or "—"))


def _es_registrado(usuario: Usuario | None) -> bool:
    return bool(usuario and usuario.rol != "guest")


def _safe_send(to, subject, html, cuenta="ventas", reply_to=None):
    # Nunca corta el flujo que lo llama (checkout, webhook): solo registra.
    # logger y no print(): en el servidor stdout es ASCII.
    if not to:
        current_app.logger.warning("EMAIL: destinatario vacio, se ignora: %r", subject)
        return
    try:
        send_email_async(to=to, subject=subject, html=html, cuenta=cuenta, reply_to=reply_to)
    except Exception:
        current_app.logger.exception("EMAIL ERROR: to=%r subject=%r", to, subject)


def _items_html(pedido: Pedido) -> str:
    """Tabla de productos + envío + total, para cliente y admin."""
    filas = ""
    for d in pedido.detalles:
        nombre = _e(d.producto.nombre if d.producto else f"Producto #{d.producto_id}")
        filas += (
            "<tr>"
            f"<td style='padding:8px 0;color:#2a212a;font-size:14px;border-bottom:1px solid #f4e5ee;'>{nombre}"
            f"<span style='color:#8a6f86;'> × {int(d.cantidad)}</span></td>"
            f"<td style='padding:8px 0;color:#2a212a;font-size:14px;text-align:right;white-space:nowrap;"
            f"border-bottom:1px solid #f4e5ee;'>{_money(d.subtotal)}</td>"
            "</tr>"
        )
    envio = float(pedido.costo_envio or 0)
    filas += (
        "<tr>"
        "<td style='padding:8px 0;color:#8a6f86;font-size:13px;'>Envío</td>"
        f"<td style='padding:8px 0;color:#8a6f86;font-size:13px;text-align:right;'>"
        f"{_money(envio) if envio > 0 else 'A coordinar / sin cargo'}</td>"
        "</tr>"
    )
    return (
        "<div class='info-card'>"
        "<table width='100%' cellpadding='0' cellspacing='0'>"
        f"{filas}"
        "</table></div>"
    )


def _fila(label, valor, primera=False, highlight=False) -> str:
    pad = "" if primera else " style=\"padding-top:12px;\""
    cls = "info-value highlight" if highlight else "info-value"
    return f"<tr><td class=\"info-label\"{pad}>{label}</td><td class=\"{cls}\"{pad}>{valor}</td></tr>"


def _boton(url: str, texto: str, secundario=False) -> str:
    cls = "cta-button secondary" if secundario else "cta-button"
    return f'<div class="cta-wrapper"><a href="{_e(url)}" class="{cls}">{texto}</a></div>'


def _link_pedidos(usuario: Usuario | None) -> str:
    """Los registrados ven sus pedidos en /perfil; los invitados no tienen cuenta."""
    if _es_registrado(usuario):
        return _boton(f"{_frontend_url()}/perfil/", "Ver mis pedidos", secundario=True)
    return ""


def _base_template(content: str, preview_text: str = "") -> str:
    """
    Envuelve el contenido en el layout general de Caricias.
    Estética del front: fondo claro, acentos lavanda, tipografías modernas,
    inspirado en la pluma lila del logo.
    Usa tablas para compatibilidad máxima con clientes de correo.
    """
    frontend = _frontend_url()
    feather_url = f"{frontend}/caricias-logo-pluma.png"

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
          Recibís este correo por tu actividad en Caricias.<br/>
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
    nombre = _nombre(usuario)
    content = f"""
      <span class="status-badge">Cuenta creada</span>
      <h1 class="greeting">Bienvenida/o,<br/>{nombre}.</h1>
      <p class="body-text">
        Tu cuenta en <strong style="color:#2a212a;">Caricias</strong> fue creada exitosamente
        con el email <strong style="color:#2a212a;">{_e(usuario.email)}</strong>.
      </p>
      <p class="body-text">
        Desde tu perfil podés explorar nuestro catálogo, realizar compras y hacer
        seguimiento de tus pedidos con total discreción.
      </p>
      <div class="success-box">
        <p class="body-text">Tu información está protegida y tu privacidad, garantizada.</p>
      </div>
      {_boton(f"{_frontend_url()}/catalogo/", "Explorar catálogo")}
    """
    _safe_send(
        usuario.email,
        "Bienvenida/o a Caricias",
        _base_template(content, preview_text=f"Hola {nombre}, tu cuenta está lista."),
        cuenta="soporte",
    )


def send_user_order_created(usuario: Usuario, pedido: Pedido, pago: Pago):
    """Pedido creado con Mercado Pago / débito / crédito: incluye el link de pago."""
    nombre = _nombre(usuario)
    vence = _fecha(pedido.expires_at)
    pagar = _boton(pago.url_checkout, "Pagar ahora") if pago.url_checkout else ""
    content = f"""
      <span class="status-badge">Pedido recibido</span>
      <h1 class="greeting">¡Gracias por tu pedido,<br/>{nombre}!</h1>
      <p class="body-text">
        Registramos tu pedido <strong style="color:#2a212a;">#{pedido.id}</strong>.
        Para confirmarlo, completá el pago con <strong style="color:#2a212a;">{_metodo(pago)}</strong>.
        Si ya lo pagaste, ignorá este botón: te vamos a avisar cuando se acredite.
      </p>
      {_items_html(pedido)}
      <div class="info-card">
        <table width="100%" cellpadding="0" cellspacing="0">
          {_fila("Pedido", f"#{pedido.id}", primera=True, highlight=True)}
          {_fila("Método de pago", _metodo(pago))}
          {_fila("Total a pagar", _money(pago.monto), highlight=True)}
          {_fila("Reservado hasta", vence) if vence else ""}
        </table>
      </div>
      {pagar}
      <p class="body-text" style="font-size:13px;color:#8a6f86;">
        Si no completás el pago antes del vencimiento, la reserva de los productos se libera.
        El envío se realiza en embalaje neutro y discreto, sin identificación del remitente.
      </p>
      {_link_pedidos(usuario)}
    """
    _safe_send(
        usuario.email,
        f"Recibimos tu pedido #{pedido.id}",
        _base_template(content, preview_text=f"Pedido #{pedido.id} · {_money(pago.monto)} · completá el pago."),
    )


def send_user_transfer_instructions(usuario: Usuario, pedido: Pedido, pago: Pago, instrucciones: dict):
    """Pedido creado con transferencia: datos bancarios y cómo enviar el comprobante."""
    nombre = _nombre(usuario)
    vence = _fecha(pedido.expires_at)
    cbu = instrucciones.get("cbu")
    content = f"""
      <span class="status-badge">Transferencia bancaria</span>
      <h1 class="greeting">¡Gracias por tu pedido,<br/>{nombre}!</h1>
      <p class="body-text">
        Para confirmar tu pedido <strong style="color:#2a212a;">#{pedido.id}</strong>,
        transferí el monto indicado a los siguientes datos.
      </p>
      {_items_html(pedido)}
      <div class="info-card">
        <table width="100%" cellpadding="0" cellspacing="0">
          {_fila("Monto a transferir", _money(pago.monto), primera=True, highlight=True)}
          {_fila("Concepto", _e(instrucciones.get("concepto", f"PEDIDO {pedido.id}")))}
          {_fila("Reservado hasta", vence) if vence else ""}
        </table>
      </div>
      <p class="body-text" style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#8a6f86;margin-bottom:8px;">
        Datos bancarios
      </p>
      <div class="bank-block">
        <div class="bank-field">
          <div class="bank-label">Alias</div>
          <div class="bank-value">{_e(instrucciones.get("alias", "—"))}</div>
        </div>
        {f'''<div class="bank-field">
          <div class="bank-label">CBU / CVU</div>
          <div class="bank-value" style="font-size:14px;letter-spacing:1.5px;">{_e(cbu)}</div>
        </div>''' if cbu else ""}
        <div class="bank-field">
          <div class="bank-label">Titular</div>
          <div class="bank-value">{_e(instrucciones.get("titular", "—"))}</div>
        </div>
      </div>
      <div class="success-box">
        <p class="body-text">
          Cuando hagas la transferencia, <strong>respondé este mail con el comprobante</strong>.
          Apenas verifiquemos la acreditación, preparamos tu pedido.
        </p>
      </div>
      <p class="body-text" style="font-size:13px;color:#8a6f86;">
        Si no recibimos la transferencia antes del vencimiento, la reserva de los productos se libera.
      </p>
      {_link_pedidos(usuario)}
    """
    _safe_send(
        usuario.email,
        f"Datos para transferir · Pedido #{pedido.id}",
        _base_template(content, preview_text=f"Transferí {_money(pago.monto)} para confirmar tu pedido #{pedido.id}."),
    )


def send_user_payment_approved(usuario: Usuario, pedido: Pedido, pago: Pago):
    nombre = _nombre(usuario)
    content = f"""
      <span class="status-badge">Pago aprobado</span>
      <h1 class="greeting">¡Pago confirmado,<br/>{nombre}!</h1>
      <p class="body-text">
        Tu pago fue procesado exitosamente. Ya estamos preparando tu pedido
        para que llegue a vos lo antes posible.
      </p>
      {_items_html(pedido)}
      <div class="info-card">
        <table width="100%" cellpadding="0" cellspacing="0">
          {_fila("Pedido", f"#{pedido.id}", primera=True, highlight=True)}
          {_fila("Monto abonado", _money(pago.monto))}
          {_fila("Método", _metodo(pago))}
        </table>
      </div>
      <p class="body-text">
        Te avisaremos cuando tu pedido sea despachado. El envío se realiza en
        embalaje neutro y discreto.
      </p>
      {_link_pedidos(usuario)}
    """
    _safe_send(
        usuario.email,
        f"Pago aprobado · Pedido #{pedido.id}",
        _base_template(content, preview_text=f"Tu pago de {_money(pago.monto)} fue confirmado."),
    )


def send_user_payment_rejected(usuario: Usuario, pedido: Pedido, pago: Pago):
    nombre = _nombre(usuario)
    detalle = _e(pago.detalle_estado or "Sin detalle disponible")
    reintentar = _boton(pago.url_checkout, "Reintentar pago") if pago.url_checkout else ""
    content = f"""
      <span class="status-badge" style="background:#fdf2f2;border-color:#f5d0d0;color:#c0392b;">Pago rechazado</span>
      <h1 class="greeting">Hubo un problema<br/>con tu pago, {nombre}.</h1>
      <p class="body-text">
        El pago del pedido <strong style="color:#2a212a;">#{pedido.id}</strong>
        no pudo procesarse. Tu pedido sigue reservado y podés reintentar el pago.
      </p>
      <div class="alert-box">
        <p class="body-text">Motivo: <strong>{detalle}</strong></p>
      </div>
      <p class="body-text">
        Podés intentar con otra tarjeta o medio de pago. Si el problema persiste,
        respondé este mail y te ayudamos.
      </p>
      {reintentar}
    """
    _safe_send(
        usuario.email,
        f"Problema con tu pago · Pedido #{pedido.id}",
        _base_template(content, preview_text="Tu pago no pudo procesarse. Podés reintentarlo."),
    )


# ─────────────────────────────────────────────
#  Notificaciones al admin
# ─────────────────────────────────────────────

def _admin_cliente_rows(usuario: Usuario | None) -> list[tuple]:
    if not usuario:
        return [("Cliente", "desconocido")]
    filas = [
        ("Cliente", f"{_e(usuario.nombre or '—')} ({'invitado' if usuario.rol == 'guest' else 'registrado'})"),
        ("Email", _e(usuario.email)),
        ("Teléfono", _e(usuario.telefono or "—")),
    ]
    d = getattr(usuario, "direccion", None)
    if d:
        partes = [d.calle, d.departamento, d.provincia, d.codigo_postal, d.pais]
        filas.append(("Dirección (perfil)", _e(", ".join(str(p) for p in partes if p))))
    return filas


def _admin_html(title: str, rows: list[tuple], pedido: Pedido | None = None, nota: str = "") -> str:
    rows_html = "".join(
        f"<tr>"
        f"<td style='padding:8px 14px;color:#8a6f86;font-size:12px;letter-spacing:1px;"
        f"text-transform:uppercase;border-bottom:1px solid #f4e5ee;white-space:nowrap;'>{k}</td>"
        f"<td style='padding:8px 14px;color:#2a212a;font-size:14px;font-weight:600;"
        f"border-bottom:1px solid #f4e5ee;'>{v}</td>"
        f"</tr>"
        for k, v in rows
    )
    items = ""
    if pedido is not None:
        items = "".join(
            f"<tr><td style='padding:6px 14px;font-size:14px;color:#2a212a;'>"
            f"{_e(d.producto.nombre if d.producto else f'Producto #{d.producto_id}')} × {int(d.cantidad)}</td>"
            f"<td style='padding:6px 14px;font-size:14px;color:#2a212a;text-align:right;white-space:nowrap;'>{_money(d.subtotal)}</td></tr>"
            for d in pedido.detalles
        )
        items += (
            f"<tr><td style='padding:6px 14px;font-size:13px;color:#8a6f86;'>Envío</td>"
            f"<td style='padding:6px 14px;font-size:13px;color:#8a6f86;text-align:right;'>{_money(pedido.costo_envio)}</td></tr>"
        )
        items = (
            "<p style='margin:20px 0 8px;color:#8a6f86;font-size:12px;letter-spacing:1px;text-transform:uppercase;'>Productos</p>"
            f"<table style='border-collapse:collapse;width:100%;background:#fbf6f9;border-radius:8px;'>{items}</table>"
        )
    nota_html = (
        f"<p style='margin:20px 0 0;padding:12px 14px;background:#fff7e6;border:1px solid #f5d9a8;"
        f"border-radius:8px;font-size:14px;color:#7a5a12;'>{nota}</p>" if nota else ""
    )
    return f"""
    <div style="background:#ffffff;font-family:'DM Sans',Arial,sans-serif;padding:24px;
                border:1px solid #e8d6e4;border-radius:12px;color:#2a212a;max-width:580px;margin:24px auto;">
      <p style="font-family:'Space Grotesk',Georgia,serif;font-size:16px;margin:0 0 16px;
                color:#b07aa8;font-weight:600;letter-spacing:0.5px;">{title}</p>
      <table style="border-collapse:collapse;width:100%;background:#fbf6f9;border-radius:8px;overflow:hidden;">
        {rows_html}
      </table>
      {items}
      {nota_html}
    </div>
    """


def send_admin_payment_approved(pedido: Pedido, pago: Pago, usuario: Usuario | None):
    html = _admin_html(f"💰 Pago aprobado · Pedido #{pedido.id}", [
        ("Pedido", f"#{pedido.id}"),
        ("Monto", _money(pago.monto)),
        ("Método", _metodo(pago)),
        ("Pago MP", _e(pago.id_pago_mp or "—")),
        ("Estado pedido", _e(ESTADOS_PEDIDO.get(pedido.estado, pedido.estado))),
        *_admin_cliente_rows(usuario),
    ], pedido=pedido, nota="Preparar el envío. Coordinar dirección con el cliente si no figura arriba.")
    _safe_send(_admin_email(), f"[Caricias] Pago aprobado · Pedido #{pedido.id} · {_money(pago.monto)}", html)


def send_admin_payment_rejected(pedido: Pedido, pago: Pago, usuario: Usuario | None):
    html = _admin_html(f"Pago rechazado · Pedido #{pedido.id}", [
        ("Pedido", f"#{pedido.id}"),
        ("Monto", _money(pago.monto)),
        ("Método", _metodo(pago)),
        ("Motivo", _e(pago.detalle_estado or "—")),
        *_admin_cliente_rows(usuario),
    ])
    _safe_send(_admin_email(), f"[Caricias] Pago rechazado · Pedido #{pedido.id}", html)


def send_admin_transfer_order(pedido: Pedido, pago: Pago, usuario: Usuario | None):
    html = _admin_html(f"🏦 Nuevo pedido por transferencia · #{pedido.id}", [
        ("Pedido", f"#{pedido.id}"),
        ("Monto a recibir", _money(pago.monto)),
        ("Concepto", f"PEDIDO {pedido.id}"),
        ("Reservado hasta", _fecha(pedido.expires_at) or "—"),
        *_admin_cliente_rows(usuario),
    ], pedido=pedido,
        nota="El cliente va a responder el mail de instrucciones con el comprobante. "
             "Verificá la acreditación en la cuenta y pasá el pedido a PAGADO desde el panel.")
    _safe_send(_admin_email(), f"[Caricias] Transferencia a verificar · Pedido #{pedido.id} · {_money(pago.monto)}", html)
