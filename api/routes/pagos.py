from database import db
import os
import hmac
import hashlib
import logging
import mercadopago
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Pedido, Pago, Usuario, Producto
from services.notifications import (
    send_user_payment_approved,
    send_user_payment_rejected,
    send_admin_payment_approved,
    send_admin_payment_rejected,
    send_user_transfer_instructions
)

pagos_bp = Blueprint("pagos", __name__, url_prefix="/pagos")

MONTO_TOLERANCIA = 1.0  # ARS

_mp_token = os.getenv("MP_ACCESS_TOKEN")
if not _mp_token:
    logging.warning("MP_ACCESS_TOKEN no está configurado. Los pagos con MercadoPago no funcionarán.")
sdk = mercadopago.SDK(_mp_token or "")


def _verify_mp_signature(req, payment_id):
    """
    Valida la cabecera x-signature de Mercado Pago.
    Formato del header: "ts=<timestamp>,v1=<hmac_sha256_hex>"
    Manifest a firmar: "id:<payment_id>;request-id:<x-request-id>;ts:<ts>;"
    Clave: MP_WEBHOOK_SECRET (Tus integraciones -> Webhooks -> Clave secreta).
    Devuelve True si la firma es valida.
    """
    secret = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
    if not secret:
        # Sin secreto configurado no se puede verificar -> rechazar
        return False

    x_signature = req.headers.get("x-signature") or req.headers.get("X-Signature")
    x_request_id = req.headers.get("x-request-id") or req.headers.get("X-Request-Id")
    if not x_signature or not x_request_id or not payment_id:
        return False

    ts = None
    received_hash = None
    for part in x_signature.split(","):
        part = part.strip()
        if part.startswith("ts="):
            ts = part[3:]
        elif part.startswith("v1="):
            received_hash = part[3:]

    if not ts or not received_hash:
        return False

    manifest = f"id:{payment_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, received_hash)

# metodo_pago (elección del usuario) → tipo_pago (valor MP)
METODO_PAGO_MAP = {
    "debito":       "debit_card",
    "credito":      "credit_card",
    "mercadopago":  "account_money",
    "transferencia": "bank_transfer",
}

@pagos_bp.route("/webhook", methods=["POST", "GET"])
def webhook_mp():
    try:
        data = request.get_json(silent=True) or {}

        # Formato webhook (JSON body)
        event_type = data.get("type")
        action = data.get("action")
        payment_id = None
        if isinstance(data.get("data"), dict):
            payment_id = data["data"].get("id")

        # Formato IPN legacy (query params): ?id=xxx&topic=payment
        if not payment_id:
            topic = request.args.get("topic")
            if topic == "payment":
                payment_id = request.args.get("id")
                event_type = "payment"

        current_app.logger.info(
            "MP WEBHOOK: action=%s type=%s payment_id=%s",
            action, event_type, payment_id,
        )

        if event_type != "payment" or not payment_id:
            return jsonify({"status": "ignored"}), 200

        # Verificacion de firma HMAC SHA256 con MP_WEBHOOK_SECRET.
        # TEMPORAL: sin secreto configurado se omite la verificacion. Es tolerable
        # porque el estado no se toma del body: se consulta a la API de MP con
        # el access token. Cargar MP_WEBHOOK_SECRET para volver a exigirla.
        if not (os.getenv("MP_WEBHOOK_SECRET") or "").strip():
            current_app.logger.warning(
                "MP WEBHOOK sin MP_WEBHOOK_SECRET: firma NO verificada (payment_id=%s, ip=%s)",
                payment_id, request.remote_addr,
            )
        elif not _verify_mp_signature(request, payment_id):
            current_app.logger.warning(
                "MP WEBHOOK firma invalida (payment_id=%s, ip=%s)",
                payment_id, request.remote_addr,
            )
            return jsonify({"error": "firma_invalida"}), 401

        pago_info = sdk.payment().get(payment_id)
        pago = (pago_info or {}).get("response") or {}
        if not pago:
            current_app.logger.warning("MP SDK sin response: %r", pago_info)
            return jsonify({"status": "no_response"}), 200

        estado = pago.get("status")

        referencia = pago.get("external_reference")
        if not referencia:
            return jsonify({"status": "no_external_reference"}), 200

        pago_reg = Pago.query.get(int(referencia))
        if not pago_reg:
            return jsonify({"status": "pago_not_found"}), 200

        # idempotencia: ignorar solo si el payment_id Y el estado ya son iguales
        if pago_reg.id_pago_mp == str(payment_id) and pago_reg.estado == estado:
            return jsonify({"status": "ok"}), 200

        pedido = Pedido.query.get(pago_reg.pedido_id)
        if not pedido:
            return jsonify({"status": "pedido_not_found"}), 200

        # Monto y moneda deben coincidir con lo que se cobró al crear la preferencia.
        # pago_reg.monto NO se pisa con lo que informa MP: es el monto esperado.
        # Tolerancia de $1 por el redondeo de unit_price en los items.
        monto_esperado = float(pago_reg.monto or 0)
        monto_recibido = float(pago.get("transaction_amount") or 0)
        moneda = pago.get("currency_id")
        pago_valido = moneda == "ARS" and abs(monto_recibido - monto_esperado) <= MONTO_TOLERANCIA
        if not pago_valido:
            current_app.logger.warning(
                "MP WEBHOOK pago no coincide (pago_id=%s, payment_id=%s, esperado=%.2f ARS, recibido=%.2f %s)",
                pago_reg.id, payment_id, monto_esperado, monto_recibido, moneda,
            )

        previous_estado = pago_reg.estado
        pago_reg.id_pago_mp = str(payment_id)
        pago_reg.estado = estado
        pago_reg.detalle_estado = pago.get("status_detail") if pago_valido else "monto_o_moneda_no_coincide"
        pago_reg.tipo_pago = pago.get("payment_type_id")  # credit_card | debit_card | account_money | …
        pago_reg.id_orden_mercante = str((pago.get("order") or {}).get("id"))

        if estado == "approved":
            if not pago_valido:
                # no confirmar stock ni marcar pagado → revisión manual
                pedido.estado = "REVISAR"
            elif pedido.estado == "EXPIRADO":
                # pago aprobado pero pedido vencido → revisión manual
                pedido.estado = "REVISAR"   # o "PAGO_TARDE"
            else:
                pedido.estado = "PAGADO"
                pedido.stock_state = "confirmed"
                pedido.expires_at = None

        elif estado in ("pending", "in_process", "in_mediation"):
            # Ojo: acá vos estabas usando "PENDIENTE" pero tu sistema usa "PENDIENTE_PAGO"
            pedido.estado = "PENDIENTE_PAGO"

        elif estado == "rejected":
            if pedido.estado == "EXPIRADO":
                pass
            else:
                pedido.estado = "RECHAZADO"
                if pedido.stock_state == "reserved":
                    for d in pedido.detalles:
                        prod = Producto.query.get(d.producto_id)
                        if prod:
                            prod.stock += d.cantidad
                    pedido.stock_state = "released"
        else:
            pedido.estado = "PENDIENTE_PAGO"

              
        db.session.commit()
        
        # ✅ Envío de mails solo si cambió el estado
        if estado != previous_estado:
            usuario = Usuario.query.get(pedido.usuario_id)

            if estado == "approved":
                # Usuario (si el monto no coincide, el admin revisa antes de avisarle)
                if usuario and pago_valido and (pago_reg.ultimo_estado_notificado != "approved"):
                    send_user_payment_approved(usuario, pedido, pago_reg)

                # Admin
                if usuario and not pago_reg.notificado_admin:
                    send_admin_payment_approved(pedido, pago_reg, usuario)

                pago_reg.ultimo_estado_notificado = "approved"
                pago_reg.notificado_user = True
                pago_reg.notificado_admin = True
                db.session.commit()

            elif estado == "rejected":
                if usuario and (pago_reg.ultimo_estado_notificado != "rejected"):
                    send_user_payment_rejected(usuario, pedido, pago_reg)

                # Admin
                if not pago_reg.notificado_admin:
                    send_admin_payment_rejected(pedido, pago_reg, usuario)

                pago_reg.ultimo_estado_notificado = "rejected"
                pago_reg.notificado_user = True
                pago_reg.notificado_admin = True
                db.session.commit()
                
        return jsonify({"status": "ok"}), 200
    
    except Exception:
        # IMPORTANTÍSIMO: no tires 500 si querés evitar reintentos infinitos por algo que es tu bug
        current_app.logger.exception("ERROR WEBHOOK MP")
        return jsonify({"status": "error_logged"}), 200


@pagos_bp.route("/preferencia", methods=["POST"])
@jwt_required(optional=True)
def crear_preferencia_pago():
    try:
        data = request.get_json() or {}

        pedido_id = data.get("pedido_id")
        metodo_pago = data.get("tipo_pago")  # debito | credito | mercadopago | transferencia
        if metodo_pago not in METODO_PAGO_MAP:
            return jsonify({"error": f"tipo_pago inválido. Valores aceptados: {list(METODO_PAGO_MAP.keys())}"}), 400
        tipo_pago_mp = METODO_PAGO_MAP[metodo_pago]

        pedido = Pedido.query.get(pedido_id)
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404

        if pedido.estado != "PENDIENTE_PAGO":
            return jsonify({"error": f"El pedido no está en estado válido para pagar (estado: {pedido.estado})"}), 400

        identity = get_jwt_identity()
        if identity:
            # Usuario logueado: debe ser el dueño del pedido
            if int(identity) != pedido.usuario_id:
                return jsonify({"error": "No autorizado para este pedido"}), 403
        else:
            # Invitado: debe presentar el claim_token entregado al crear el pedido
            claim_token = data.get("claim_token") or ""
            if not pedido.claim_token or not hmac.compare_digest(claim_token, pedido.claim_token):
                return jsonify({"error": "No autorizado para este pedido"}), 403

        detalles = pedido.detalles
        costo_envio = float(pedido.costo_envio or 0)

        if not detalles:
            return jsonify({"error": "El pedido no tiene items"}), 400

        # =====================================================
        # 0) Si el pago es por transferencia → NO usar Mercado Pago
        # =====================================================
        if metodo_pago == "transferencia":
            pago = Pago(
                pedido_id=pedido_id,
                referencia_externa=str(pedido_id),
                estado="pendiente",
                detalle_estado="awaiting_transfer",
                metodo_pago="transferencia",
                tipo_pago="bank_transfer",
                monto=pedido.total,
            )
            db.session.add(pago)
            db.session.flush()
            pago.id_preferencia = f"TRANSFER-{pago.id}"
            db.session.commit()

            instrucciones = {
                "alias": "caricias.sex.mp",
                "titular": "Elisa Gramage",
                "concepto": f"PEDIDO {pedido_id}"
            }
            
            usuario = Usuario.query.get(pedido.usuario_id)
            if usuario:
                send_user_transfer_instructions(usuario, pedido, pago, instrucciones)
            return jsonify({
                "mensaje": "Transferencia registrada",
                "pedido_id": pedido_id,
                "monto": pedido.total,
                "referencia": str(pedido_id),
                "instrucciones": instrucciones
            }), 201

        # =====================================================
        # 1) Armamos items Mercado Pago (precios del momento del pedido)
        # =====================================================
        mp_items = []
        subtotal_productos = 0.0

        for d in detalles:
            prod = d.producto
            if not prod:
                return jsonify({"error": f"Producto no encontrado: {d.producto_id}"}), 404

            unit_price = round(float(d.subtotal) / int(d.cantidad), 2)
            qty = int(d.cantidad)
            subtotal_productos += float(d.subtotal)

            mp_items.append({
                "id": str(prod.id),
                "title": prod.nombre,
                "quantity": qty,
                "unit_price": unit_price,
                "currency_id": "ARS"
            })

        # =====================================================
        # 2) Costo de envio y recargo por credito
        # =====================================================
        total = subtotal_productos
        if costo_envio > 0:
            total += costo_envio
            mp_items.append({
                "id": "envio",
                "title": "Costo de envío",
                "quantity": 1,
                "unit_price": float(costo_envio),
                "currency_id": "ARS"
            })

        # crédito +10%
        if metodo_pago == "credito":
            total = round(total * 1.10, 2)
            for it in mp_items:
                it["unit_price"] = round(float(it["unit_price"]) * 1.10, 2)

        # =====================================================
        # 3) Restricciones según tipo pago
        # =====================================================
        payment_rules = build_payment_restrictions(metodo_pago)

        # =====================================================
        # 4) Guardar pago
        # =====================================================
        pago_mp = Pago(
            pedido_id=pedido_id,
            id_preferencia=None,
            url_checkout=None,
            referencia_externa=None,
            estado="pendiente",
            metodo_pago=metodo_pago,
            tipo_pago=tipo_pago_mp,
            monto=total
        )

        db.session.add(pago_mp)
        db.session.commit()
        
        # =====================================================
        # 5) Crear preferencia
        # =====================================================
        preference_data = {
            "items": mp_items,
            "external_reference": str(pago_mp.id), 
            "back_urls": {
                "success": f"https://cariciassexshop.com/pagos?status=success&pedido_id={pedido_id}",
                "failure": "https://cariciassexshop.com/pagos?status=failure",
                "pending": f"https://cariciassexshop.com/pagos?status=pending&pedido_id={pedido_id}"
            },
            "auto_return": "approved",
            "binary_mode": True
        }

        # strip(): un espacio en el .env hace que MP rechace la URL por formato
        notification_url = (os.getenv("MP_NOTIFICATION_URL") or "").strip()
        if notification_url:
            preference_data["notification_url"] = notification_url


        # Agregar reglas de pagos SOLO si existen
        if payment_rules is not None:
            preference_data["payment_methods"] = payment_rules
        
        
        pref_info = sdk.preference().create(preference_data)
        pref = pref_info.get("response", {})
        
        if "id" not in pref:
            raise Exception(f"MercadoPago Error: {pref_info}")

        # =====================================================
        # 6) Actualizar el mismo Pago con la preferencia
        # =====================================================
        pago_mp.id_preferencia = pref["id"]
        pago_mp.url_checkout = pref["init_point"]
        pago_mp.referencia_externa = str(pago_mp.id)  # opcional
        db.session.commit()

        return jsonify({
            "preference_id": pref["id"],
            "init_point": pref["init_point"],
            "pedido_id": pedido_id,
            "pago_id": pago_mp.id
        }), 201


    except Exception:
        current_app.logger.exception("ERROR crear_preferencia_pago")
        return jsonify({"error": "Error interno"}), 500

def build_payment_restrictions(tipo_pago):

    # Plantilla base requerida por Mercado Pago
    rules = {
        "excluded_payment_types": [],
        "excluded_payment_methods": []
    }

    if tipo_pago == "debito":
        rules["excluded_payment_types"] = [
            {"id": "credit_card"},
            {"id": "ticket"},
            {"id": "bank_transfer"},
            {"id": "atm"},
            {"id": "digital_wallet"},
            {"id": "prepaid_card"}
        ]
        return rules

    if tipo_pago == "credito":
        rules["excluded_payment_types"] = [
            {"id": "debit_card"},
            {"id": "ticket"},
            {"id": "bank_transfer"},
            {"id": "atm"},
            {"id": "digital_wallet"},
            {"id": "prepaid_card"}
        ]
        return rules

    if tipo_pago == "mercadopago":  # debe coincidir con la clave de METODO_PAGO_MAP
        rules["excluded_payment_types"] = [
            {"id": "credit_card"},
            {"id": "debit_card"},
            {"id": "ticket"},
            {"id": "bank_transfer"},
            {"id": "atm"},
            {"id": "prepaid_card"}
        ]
        return rules

    if tipo_pago == "transferencia":
        return None

    # Si permite todo → retornar reglas vacías PERO válidas
    return rules
