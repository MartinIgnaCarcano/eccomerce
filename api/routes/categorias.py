import os
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Categoria, Producto, Usuario
from sqlalchemy import func, distinct
from services.uploads import is_imagen_valida

categorias_bp = Blueprint("categorias", __name__, url_prefix="/categorias")

UPLOAD_FOLDER = "static/imagenes/categorias"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

def require_admin():
    user_id = get_jwt_identity()
    user = Usuario.query.get(int(user_id))
    if not user or user.rol != "admin":
        return None
    return user

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def nombreArchivoFinal(filename, nombre, id):
    return str(id) + "_" + nombre + "." + filename.rsplit('.', 1)[1].lower()

# Crear categoría
@categorias_bp.route("/", methods=["POST"])
@jwt_required()
def crear_categoria():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        nombre = request.form.get("nombre")
        slug = request.form.get("slug")
        icon_key = request.form.get("icon_key")
        if not nombre:
            return jsonify({"msg": "Falta nombre"}), 400
        if not slug:
            return jsonify({"msg": "Falta el slug"}),400
        if not icon_key:
            return jsonify({"msg": "Falta el icon_key"}),400
        categoria = Categoria(nombre=nombre, slug=slug, icon_key=icon_key)
        
        db.session.add(categoria)
        db.session.flush()  
        # Imagen
        if "imagen" in request.files:
            file = request.files["imagen"]
            if file and allowed_file(file.filename) and is_imagen_valida(file):
                filename = secure_filename(nombreArchivoFinal(file.filename, nombre, categoria.id))
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                categoria.url_imagen = f"/{filepath}"

        db.session.commit()
        return jsonify({"id": categoria.id, "nombre": categoria.nombre, "url_imagen": categoria.url_imagen}), 201
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500

@categorias_bp.route("/", methods=["GET"])
def listar_categorias():
    try:
        categorias = (
            db.session.query(
                Categoria.id,
                Categoria.nombre,
                Categoria.url_imagen,
                Categoria.icon_key,
                func.count(distinct(Producto.id)).label("cantidad_productos")
            )
            # join por relación many-to-many
            .outerjoin(Categoria.productos)  # equivalente a join pivote + productos
            # si querés contar solo los productos visibles
            .filter((Producto.activo == True) | (Producto.id == None))
            .group_by(Categoria.id, Categoria.nombre, Categoria.url_imagen, Categoria.icon_key)
            .order_by(func.count(distinct(Producto.id)).desc())
            .all()
        )

        data = [
            {
                "id": c.id,
                "nombre": c.nombre,
                "url_imagen": c.url_imagen,
                "cantidad_productos": int(c.cantidad_productos or 0),
                "icon_key": c.icon_key
            }
            for c in categorias
        ]

        return jsonify(data), 200

    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500
    
# Obtener una categoría
@categorias_bp.route("/<int:id>", methods=["GET"])
def detalle_categoria(id):
    try:
        c = Categoria.query.get_or_404(id)
        return jsonify({"id": c.id, "nombre": c.nombre, "url_imagen": c.url_imagen, "slug": c.slug, "icon_key": c.icon_key})
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500

# Actualizar categoría
@categorias_bp.route("/<int:id>", methods=["PUT", "PATCH"])
@jwt_required()
def actualizar_categoria(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        c = Categoria.query.get_or_404(id)
        nombre = request.form.get("nombre")
        if nombre:
            c.nombre = nombre
            
        icon_key = request.form.get("icon_key")
        if icon_key:
            c.icon_key = icon_key
            
        if "imagen" in request.files:
            file = request.files["imagen"]
            if file and allowed_file(file.filename) and is_imagen_valida(file):
                filename = secure_filename(file.filename)
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                c.url_imagen = f"/{filepath}"

        db.session.commit()
        return jsonify({"msg": "Categoría actualizada", "id": c.id, "nombre": c.nombre, "url_imagen": c.url_imagen})
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500

#Eliminar categoría
@categorias_bp.route("/<int:id>", methods=["DELETE"])
@jwt_required()
def eliminar_categoria(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        c = Categoria.query.get_or_404(id)
        
        # Eliminar imagen del filesystem si existe
        if c.url_imagen:
            # La url en DB es algo como "/static/imagenes/categorias/imagen.jpg"
            # Convertimos a path absoluto
            imagen_path = c.url_imagen.lstrip("/")  # quitar la barra inicial
            if os.path.exists(imagen_path):
                try:
                    os.remove(imagen_path)
                except Exception as e:
                    print(f"No se pudo eliminar la imagen: {e}")
        
        db.session.delete(c)
        db.session.commit()
        return jsonify({"msg": "Categoría eliminada"})
    except Exception as e:
        db.session.rollback()
        print("ERROR:", repr(e))
        return jsonify({"error": "Error interno"}), 500
    
