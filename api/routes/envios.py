from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import ZonaEnvio, Usuario
from database import db
import requests

envios_bp = Blueprint("zona_envios", __name__, url_prefix="/envios")

def require_admin():
    user_id = get_jwt_identity()
    user = Usuario.query.get(int(user_id))
    if not user or user.rol != "admin":
        return None
    return user

@envios_bp.route("/", methods=["GET"])
def listar_zonas():
    try:
        zonas = ZonaEnvio.query.all()
        return jsonify([z.to_dict() for z in zonas])
    except Exception:
        db.session.rollback()
        current_app.logger.exception("envios endpoint failed")
        return jsonify({"error": "Error interno"}), 500
    
@envios_bp.route("/<int:zona_id>", methods=["GET"])
def obtener_zona(zona_id):
    try:
        zona = ZonaEnvio.query.get(zona_id)
        if not zona:
            return jsonify({"error": "Zona no encontrada"}), 404
        return jsonify(zona.to_dict())
    except Exception:
        db.session.rollback()
        current_app.logger.exception("envios endpoint failed")
        return jsonify({"error": "Error interno"}), 500
    
@envios_bp.route("/", methods=["POST"])
@jwt_required()
def crear_zona():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        data = request.get_json()

        zona = ZonaEnvio(
            nombre=data["nombre"],
            cp_inicio=data["cp_inicio"],
            cp_fin=data["cp_fin"],
            tipo_envio=data["tipo_envio"],
            precio=data["precio"],
            activa = True
        )

        db.session.add(zona)
        db.session.commit()

        return jsonify({"message": "Zona creada", "zona": zona.to_dict()}), 201
    except Exception:
        db.session.rollback()
        current_app.logger.exception("envios endpoint failed")
        return jsonify({"error": "Error interno"}), 500
    
@envios_bp.route("/<int:zona_id>", methods=["PUT", "PATCH"])
@jwt_required()
def actualizar_zona(zona_id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        zona = ZonaEnvio.query.get(zona_id)
        if not zona:
            return jsonify({"error": "Zona no encontrada"}), 404

        data = request.get_json()
        if "nombre" in data:
            zona.nombre = data.get("nombre")
        
        if "cp_inicio" in data:
            zona.cp_inicio = data.get("cp_inicio")
        
        if "cp_fin" in data:
            zona.cp_fin = data.get("cp_fin")
                
        if "tipo_envio" in data:
            zona.tipo_envio = data.get("tipo_envio")
            
        if "precio" in data:
            zona.precio = data.get("precio")
            
        if "activa" in data:
            zona.activa = data.get("activa")
        
        db.session.commit()

        return jsonify({"message": "Zona actualizada", "zona": zona.to_dict()})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("envios endpoint failed")
        return jsonify({"error": "Error interno"}), 500
    
@envios_bp.route("/<int:zona_id>", methods=["DELETE"])
@jwt_required()
def eliminar_zona(zona_id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:     
        zona = ZonaEnvio.query.get(zona_id)
        if not zona:
            return jsonify({"error": "Zona no encontrada"}), 404

        db.session.delete(zona)
        db.session.commit()

        return jsonify({"message": "Zona eliminada"})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("envios endpoint failed")
        return jsonify({"error": "Error interno"}), 500

ANDREANI_URL = "https://www.andreani.com/api/cotizador/prices"
VIACARGO_URL = "https://ws.busplus.com.ar/alerce/cotizar"

@envios_bp.route("/calcular", methods=["POST"])
def calcular_envio():
    try:
        data = request.get_json() or {}
        cp = data.get("cp")
        tipo_envio = data.get("tipo_envio")

        if not cp or not tipo_envio:
            return jsonify({"error": "cp y tipo_envio son requeridos"}), 400

        cp = str(cp).strip()
        tipo_envio_norm = str(tipo_envio).strip().lower()

        # -------------------------------------------------
        # 1) Intento externo según tipo_envio
        # -------------------------------------------------
        if tipo_envio_norm == "correo":
            print("andreani")
            # ===== Andreani (home) =====
            try:
                payload = {
                    "codigoPostalOrigen": "5519",
                    "codigoPostalDestino": cp,
                    "tipoDeEnvioId": "9c16612c-a916-48cf-9fbb-dbad2b097e9e",
                    "bultos": [
                        {
                            "itemId": "b1a076ac-5b7b-4b16-aec1-e0b90bae7c6c",
                            "altoCm": "6",
                            "anchoCm": "30",
                            "largoCm": "50",
                            "peso": "1000",
                            "unidad": "grs",
                            "valorDeclarado": "4500",
                        }
                    ],
                }

                res = requests.post(
                    ANDREANI_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0",  # a veces evita bloqueos
                    },
                    timeout=7,
                )
                res.raise_for_status()

                prices = res.json()
                home_price = None
                if isinstance(prices, list):
                    home_price = next((p.get("price") for p in prices if p.get("type") == "home"), None)

                if home_price is not None:
                    return jsonify({
                        "source": "andreani",
                        "tipo_envio": tipo_envio,
                        "precio": float(home_price),
                    }), 200

            except Exception:
                current_app.logger.exception("Andreani failed, fallback")

        else:
            # ===== ViaCargo =====
            print("viacargo")
            try:
                payload = {
                    "IdClienteRemitente": "00000511",
                    "IdCentroRemitente": "02",
                    "CodigoPostalRemitente": "5500",
                    "CodigoPostalDestinatario": cp,
                    "NumeroBultos": "1",
                    "Kilos": "1",
                    "Largo": "50",
                    "Ancho": "30",
                    "Alto": "6",
                    "ImporteValorDeclarado": "50000",
                }

                res = requests.post(
                    VIACARGO_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0",
                    },
                    timeout=10,
                )

                # ViaCargo a veces responde texto; validamos status y parseo
                if not res.ok:
                    raise RuntimeError(f"ViaCargo status={res.status_code} body={res.text[:300]}")

                data_vc = res.json()  # si devuelve texto no-json, esto tira y cae al fallback
                cot0 = (data_vc.get("Cotizacion") or [None])[0] or {}

                precio = cot0.get("TOTAL")
                descripcion = cot0.get("PRODUCTO_DESCRIPCION") or "Sin descripción"
                tiempo_entrega = cot0.get("TIEMPO_ENTREGA")

                if precio is not None:
                    # TOTAL a veces puede venir string
                    try:
                        precio_num = float(str(precio).replace(",", "."))
                    except:
                        precio_num = precio

                    return jsonify({
                        "source": "viacargo",
                        "tipo_envio": tipo_envio,
                        "precio": precio_num,
                        "descripcion": descripcion,
                        "tiempo_entrega": tiempo_entrega,
                    }), 200

                raise RuntimeError("ViaCargo no devolvió TOTAL")

            except Exception:
                current_app.logger.exception("ViaCargo failed, fallback")

        # -------------------------------------------------
        # 2) Fallback: lo que ya hacía tu endpoint (DB)
        # -------------------------------------------------
        zona = ZonaEnvio.query.filter(
            ZonaEnvio.cp_inicio <= cp,
            ZonaEnvio.cp_fin >= cp,
            ZonaEnvio.tipo_envio == tipo_envio,
            ZonaEnvio.activa == True
        ).first()

        if not zona:
            return jsonify({"error": "No hay tarifas para este CP y tipo de envío"}), 404

        return jsonify({
            "source": "zona_envio",
            "zona": zona.nombre,
            "tipo_envio": tipo_envio,
            "precio": zona.precio
        }), 200

    except Exception:
        db.session.rollback()
        current_app.logger.exception("envios endpoint failed")
        return jsonify({"error": "Error interno"}), 500