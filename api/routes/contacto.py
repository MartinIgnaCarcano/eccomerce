from flask import Blueprint, request, jsonify
from markupsafe import escape
from services.email_service import send_email
from services.ratelimit import rate_limit

contact_bp = Blueprint("contact", __name__)

@contact_bp.route("/contact", methods=["POST"])
@rate_limit(5, 60)
def contact():
    data = request.get_json()

    name = escape(data.get("name") or "")
    email = escape(data.get("email") or "")
    phone = escape(data.get("phone") or "-")
    subject = escape(data.get("subject") or "")
    message = escape(data.get("message") or "")

    if not data.get("name") or not data.get("email") or not data.get("subject") or not data.get("message"):
        return jsonify({"ok": False, "error": "Faltan campos obligatorios"}), 400

    html = f"""
        <h2>Nuevo mensaje de contacto desde la Pagina Web</h2>
        <p><strong>Nombre:</strong> {name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Teléfono:</strong> {phone}</p>
        <p><strong>Asunto:</strong> {subject}</p>
        <p><strong>Mensaje:</strong></p>
        <p>{message}</p>
    """

    try:
        send_email(
            to="soporte@cariciassexshop.com",
            subject=f"Contacto web: {data.get('subject', '')}",
            html=html,
            reply_to=data.get("email")
        )
        return jsonify({"ok": True}), 200
    except Exception:
        return jsonify({"ok": False, "error": "Error al enviar el mensaje"}), 500