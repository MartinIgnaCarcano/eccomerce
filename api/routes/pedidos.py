from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Pedido, PedidoDetalle, Producto, Usuario, Pago, now_ar
from database import db
from sqlalchemy import desc
from datetime import datetime, timedelta
from sqlalchemy import update
from decimal import Decimal
import secrets

pedidos_bp = Blueprint("pedidos", __name__,url_prefix="/pedidos")

def require_admin():
    user_id = get_jwt_identity()
    user = Usuario.query.get(int(user_id))
    if not user or user.rol != "admin":
        return None
    return user

#1440 minutos = 24hs
RESERVA_MINUTOS = 1440

#-----------------
#-----USER--------
#-----------------
@pedidos_bp.route("/", methods=["GET"], strict_slashes=False) # Listar pedidos del usuario logueado
@jwt_required()
def listar_pedidos():
    try:
        usuario_id = get_jwt_identity()
        
        if usuario_id is None:
            return jsonify({"error": "Usuario no autenticado"}), 401
        
        pedidos = (
            Pedido.query
            .filter_by(usuario_id=usuario_id)
            .order_by(desc(Pedido.fecha))
            .all()
        )

        resultado = []
        for p in pedidos:
            ultimo_pago = (
                Pago.query
                .filter_by(pedido_id=p.id)
                .order_by(Pago.fecha_creacion.desc())
                .first()
            )
            resultado.append({
                "id": p.id,
                "estado": p.estado,
                "total": p.total,
                "costo_envio": p.costo_envio,
                "fecha": p.fecha.isoformat(),
                "estado_pago": ultimo_pago.estado if ultimo_pago else None,
                "detalles": [
                    {
                        "producto": i.producto.nombre,
                        "cantidad": i.cantidad,
                        "subtotal": i.subtotal
                    } for i in p.detalles
                ]
            })

        return jsonify(resultado)
    except Exception:
        current_app.logger.exception("listar_pedidos failed")
        return jsonify({"error": "Error interno"}), 500

# Ver detalle de un pedido
@pedidos_bp.route("/unico/<int:id>", methods=["GET"])
@jwt_required()
def detalle_pedido(id):
    try:
        usuario_id = int(get_jwt_identity())
        pedido = Pedido.query.get(id)
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404
        if pedido.usuario_id != usuario_id:
            return jsonify({"error": "No autorizado"}), 403
        pago = (Pago.query
            .filter_by(pedido_id=pedido.id)
            .order_by(Pago.fecha_creacion.desc())
            .first())

        pago_data = None
        if pago:
            pago_data = {
                "estado": pago.estado,
                "metodo_pago": pago.metodo_pago,
                "moneda": pago.moneda,
                "fecha_actualizacion": pago.fecha_actualizacion.isoformat() if pago.fecha_actualizacion else None,
            }

        return jsonify({
            "id": pedido.id,
            "estado": pedido.estado,
            "total": pedido.total,
            "costo_envio": pedido.costo_envio,
            "fecha": pedido.fecha.isoformat(),
            "pago": pago_data,
            "detalles": [
                {
                    "producto": i.producto.nombre,
                    "cantidad": i.cantidad,
                    "subtotal": i.subtotal
                } for i in pedido.detalles
            ]
        })
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500    

@pedidos_bp.route("/", methods=["POST"])
@jwt_required(optional=True)
def crear_pedido():
    try:
        data = request.get_json() or {}
        detalles = data.get("detalles", [])
        if not detalles:
            return jsonify({"error": "Faltan detalles del pedido"}), 400

        # 1) usuario logueado o invitado
        identity = get_jwt_identity()   # None si no hay token
        usuario_id = int(identity) if identity is not None else None

        if usuario_id is None:
            email = (data.get("email") or "").strip().lower()
            nombre = data.get("nombre", "Invitado")
            telefono = data.get("telefono")

            if not email:
                return jsonify({"error": "Para pedidos sin registrarse, se requiere email"}), 400

            usuario = Usuario.query.filter_by(email=email).first()
            current_app.logger.info(
                "guest-checkout email=%r match_id=%s match_rol=%s",
                email,
                usuario.id if usuario else None,
                usuario.rol if usuario else None,
            )
            # No asociar el pedido a una cuenta registrada ajena (evita pedidos
            # fantasma/phishing). Se reutiliza solo un registro guest existente
            # (o uno con rol NULL, legacy pre-migración).
            if usuario and usuario.rol and usuario.rol != "guest":
                return jsonify({
                    "error": "Ese email pertenece a una cuenta registrada. Iniciá sesión para continuar."
                }), 409
            if not usuario:
                from werkzeug.security import generate_password_hash
                usuario = Usuario(
                    nombre=nombre,
                    email=email,
                    telefono=telefono,
                    rol="guest",
                    password_hash=generate_password_hash(secrets.token_urlsafe(32))
                )
                db.session.add(usuario)
                db.session.flush()  # <-- NO commit todavía

            usuario_id = usuario.id
        else:
            usuario_id = int(usuario_id)
            usuario = Usuario.query.get(usuario_id)

        # 2) reservar stock y armar detalles (todo en la misma transacción)
        total = Decimal("0.00")
        detalles_pedido = []

        for item in detalles:
            producto_id = item.get("producto_id")
            cantidad = int(item.get("cantidad", 1))

            if not producto_id or cantidad <= 0:
                db.session.rollback()
                return jsonify({"error": "Detalle inválido"}), 400

            # Traer producto (precio/nombre) - lectura
            producto = Producto.query.get(producto_id)
            if not producto or not producto.activo:
                db.session.rollback()
                return jsonify({"error": f"Producto {producto_id} no encontrado"}), 404

            # ✅ UPDATE ATÓMICO: descuenta solo si hay stock suficiente
            stmt = (
                update(Producto)
                .where(Producto.id == producto_id, Producto.stock >= cantidad)
                .values(stock=Producto.stock - cantidad)
            )
            res = db.session.execute(stmt)

            if res.rowcount == 0:
                db.session.rollback()
                return jsonify({"error": f"Stock insuficiente para {producto.nombre}"}), 400

            # subtotal usando Decimal (evita errores float)
            unit_price = Decimal(str(producto.precio))
            subtotal = (unit_price * Decimal(cantidad)).quantize(Decimal("0.01"))
            total += subtotal

            detalles_pedido.append(
                PedidoDetalle(
                    producto_id=producto_id,
                    cantidad=cantidad,
                    subtotal=float(subtotal)  # si tu columna es Numeric podés guardar Decimal directo
                )
            )

        costo_envio = Decimal(str(data.get("costo_envio", 0) or 0)).quantize(Decimal("0.01"))
        total_final = (total + costo_envio).quantize(Decimal("0.01"))

        pedido = Pedido(
            usuario_id=usuario_id,
            total=float(total_final),       # si Numeric: total=total_final
            costo_envio=float(costo_envio), # si Numeric: costo_envio=costo_envio
            estado="PENDIENTE_PAGO",
            detalles=detalles_pedido,
            expires_at=now_ar() + timedelta(minutes=RESERVA_MINUTOS),
            stock_state="reserved",
            claim_token=secrets.token_urlsafe(32)
        )

        db.session.add(pedido)

        # ✅ un solo commit al final: usuario guest + stock + pedido + detalles
        db.session.commit()

        # Sin notificaciones al crear el pedido: el cliente solo se entera si
        # elige transferencia (se notifica en /preferencia) y el admin recibe
        # aviso únicamente cuando se procesa el pago.

        return jsonify({
            "pedido_id": pedido.id,
            "total": float(total_final),
            "estado": pedido.estado,
            "usuario_id": usuario_id,
            "claim_token": pedido.claim_token
        }), 201

    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500


#-----------------
#----ADMIN--------
#-----------------
@pedidos_bp.route("/listar", methods=["GET"])
@jwt_required()
def listar_todos_pedidos():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))
        offset_value = (page - 1) * per_page

        query = Pedido.query

        estado_filter = request.args.get("estado")
        if estado_filter:
            query = query.filter(Pedido.estado == estado_filter.upper())

        nombre_filter = request.args.get("nombre")
        if nombre_filter:
            query = query.join(Usuario, Pedido.usuario_id == Usuario.id).filter(
                Usuario.nombre.ilike(f"%{nombre_filter}%")
            )

        tipo_pago_filter = request.args.get("tipo_pago")
        if tipo_pago_filter:
            query = query.filter(Pedido.pagos.any(Pago.metodo_pago == tipo_pago_filter))

        fecha_desde = request.args.get("fecha_desde")
        if fecha_desde:
            query = query.filter(Pedido.fecha >= datetime.fromisoformat(fecha_desde))

        fecha_hasta = request.args.get("fecha_hasta")
        if fecha_hasta:
            query = query.filter(Pedido.fecha <= datetime.fromisoformat(fecha_hasta))

        total = query.count()

        pedidos = (
            query
            .order_by(desc(Pedido.fecha))
            .limit(per_page)
            .offset(offset_value)
            .all()
        )

        def serializar_pago(pg):
            return {
                "id": pg.id,
                "estado": pg.estado,
                "detalle_estado": pg.detalle_estado,
                "metodo_pago": pg.metodo_pago,
                "tipo_pago": pg.tipo_pago,
                "monto": float(pg.monto) if pg.monto is not None else None,
                "id_pago_mp": pg.id_pago_mp,
                "id_preferencia": pg.id_preferencia,
                "notificado_user": pg.notificado_user,
                "notificado_admin": pg.notificado_admin,
                "fecha_creacion": pg.fecha_creacion.isoformat() if pg.fecha_creacion else None,
                "fecha_actualizacion": pg.fecha_actualizacion.isoformat() if pg.fecha_actualizacion else None,
            }

        data = []
        for p in pedidos:
            usuario = Usuario.query.get(p.usuario_id)
            pagos_ordenados = sorted(p.pagos, key=lambda pg: pg.fecha_creacion or datetime.min, reverse=True)
            ultimo_pago = pagos_ordenados[0] if pagos_ordenados else None

            data.append({
                "id": p.id,
                "estado": p.estado,
                "stock_state": p.stock_state,
                "total": float(p.total) if p.total is not None else 0,
                "costo_envio": float(p.costo_envio) if p.costo_envio is not None else 0,
                "fecha": p.fecha.isoformat() if p.fecha else None,
                "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                "usuario": {
                    "id": usuario.id,
                    "nombre": usuario.nombre,
                    "email": usuario.email,
                    "telefono": usuario.telefono,
                    "rol": usuario.rol,
                } if usuario else None,
                "detalles": [
                    {
                        "producto_id": i.producto_id,
                        "producto": i.producto.nombre if i.producto else None,
                        "cantidad": i.cantidad,
                        "subtotal": float(i.subtotal) if i.subtotal is not None else 0,
                    } for i in p.detalles
                ],
                "pago_activo": serializar_pago(ultimo_pago) if ultimo_pago else None,
                "pagos": [serializar_pago(pg) for pg in pagos_ordenados],
            })

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
            "pedidos": data
        }), 200

    except Exception:
        current_app.logger.exception("listar_pedidos_admin failed")
        return jsonify({"error": "Error interno"}), 500

@pedidos_bp.route("/<int:id>", methods=["GET"])
@jwt_required()
def detalle_pedido_admin(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        p = Pedido.query.get(id)
        if not p:
            return jsonify({"error": "Pedido no encontrado"}), 404

        usuario = Usuario.query.get(p.usuario_id)
        pagos_ordenados = sorted(p.pagos, key=lambda pg: pg.fecha_creacion or datetime.min, reverse=True)
        ultimo_pago = pagos_ordenados[0] if pagos_ordenados else None

        def serializar_pago(pg):
            return {
                "id": pg.id,
                "estado": pg.estado,
                "detalle_estado": pg.detalle_estado,
                "metodo_pago": pg.metodo_pago,
                "tipo_pago": pg.tipo_pago,
                "monto": float(pg.monto) if pg.monto is not None else None,
                "id_pago_mp": pg.id_pago_mp,
                "id_preferencia": pg.id_preferencia,
                "notificado_user": pg.notificado_user,
                "notificado_admin": pg.notificado_admin,
                "fecha_creacion": pg.fecha_creacion.isoformat() if pg.fecha_creacion else None,
                "fecha_actualizacion": pg.fecha_actualizacion.isoformat() if pg.fecha_actualizacion else None,
            }

        return jsonify({
            "id": p.id,
            "estado": p.estado,
            "stock_state": p.stock_state,
            "total": float(p.total) if p.total is not None else 0,
            "costo_envio": float(p.costo_envio) if p.costo_envio is not None else 0,
            "fecha": p.fecha.isoformat() if p.fecha else None,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
            "usuario": {
                "id": usuario.id,
                "nombre": usuario.nombre,
                "email": usuario.email,
                "telefono": usuario.telefono,
                "rol": usuario.rol,
            } if usuario else None,
            "detalles": [
                {
                    "producto_id": i.producto_id,
                    "producto": i.producto.nombre if i.producto else None,
                    "cantidad": i.cantidad,
                    "subtotal": float(i.subtotal) if i.subtotal is not None else 0,
                } for i in p.detalles
            ],
            "pago_activo": serializar_pago(ultimo_pago) if ultimo_pago else None,
            "pagos": [serializar_pago(pg) for pg in pagos_ordenados],
        }), 200

    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500


@pedidos_bp.route("/<int:id>", methods=["PATCH"]) # Actualizar estado del pedido
@jwt_required()
def actualizar_pedido(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    
    try:
        data = request.get_json() or {}
        pedido = Pedido.query.get_or_404(id)

        # Solo admin puede cambiar estado
        if "estado" in data:
            pedido.estado = data["estado"]

        db.session.commit()
        return jsonify({"message": "Pedido actualizado", "estado": pedido.estado})
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500

@pedidos_bp.route("/<int:id>", methods=["DELETE"])
@jwt_required()
def eliminar_pedido(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    
    try:
        pedido = Pedido.query.get(id)
        
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404
        db.session.delete(pedido)
        db.session.commit()
        return jsonify({"message": "Pedido eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500
    
@pedidos_bp.route("/expirar", methods=["POST"])
@jwt_required()
def expirar_pedidos():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        now = now_ar()

        expirables = (
            Pedido.query
            .filter(Pedido.estado == "PENDIENTE_PAGO")
            .filter(Pedido.expires_at.isnot(None))
            .filter(Pedido.expires_at < now)
            .all()
        )

        expired_ids = []
        released_stock_for = []

        for pedido in expirables:
            # idempotencia: si ya liberaste stock, no repetir
            if pedido.stock_state != "reserved":
                pedido.estado = "EXPIRADO"
                expired_ids.append(pedido.id)
                continue

            # devolver stock según detalles
            for d in pedido.detalles:
                prod = Producto.query.get(d.producto_id)
                if prod:
                    prod.stock += int(d.cantidad)

            pedido.stock_state = "released"
            pedido.estado = "EXPIRADO"

            expired_ids.append(pedido.id)
            released_stock_for.append(pedido.id)

        db.session.commit()

        return jsonify({
            "now_utc": now.isoformat(),
            "found": len(expirables),
            "expired": len(expired_ids),
            "released_stock_for": released_stock_for,
            "expired_ids": expired_ids
        }), 200
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500
    
    