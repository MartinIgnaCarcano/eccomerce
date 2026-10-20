import os
import time
import threading
from flask import Blueprint, json, request, jsonify, current_app
from models import ImagenProducto, Producto, Usuario, Categoria, Pedido, PedidoDetalle, Favorito, Resena, now_ar
from werkzeug.utils import secure_filename
from database import db
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import desc, asc, func, or_
from sqlalchemy.orm import selectinload
from datetime import datetime
from services.uploads import is_imagen_valida, save_imagen_optimizada

productos_bp = Blueprint("productos", __name__, url_prefix="/productos")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

def get_upload_path():
    now = datetime.now()

    year = str(now.year)
    month = f"{now.month:02d}"

    year_path = os.path.join(UPLOAD_FOLDER, year)
    month_path = os.path.join(year_path, month)

    os.makedirs(month_path, exist_ok=True)

    return year, month, month_path

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def nombreArchivoFinal(filename, nombre, id, indice):
    return str(id) + "_" + nombre + "_" + str(indice) + "." + filename.rsplit('.', 1)[1].lower()

def nombreArchivoBase(nombre, id, indice):
    return f"{id}_{nombre}_{indice}"

# Cache del indice de fotos (uploads/) usado por /admin/fotos.
# El walk del filesystem es caro; cacheamos 5 min e invalidamos en uploads/deletes.
_fotos_cache_lock = threading.Lock()
_fotos_cache = {"data": None, "ts": 0.0}
_FOTOS_TTL = 300  # segundos

def _invalidar_cache_fotos():
    with _fotos_cache_lock:
        _fotos_cache["data"] = None
        _fotos_cache["ts"] = 0.0

def _build_fotos_index():
    fotos = []
    for root, _, files in os.walk(UPLOAD_FOLDER):
        for fname in files:
            if '.' in fname and fname.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, UPLOAD_FOLDER).replace("\\", "/")
                stat = os.stat(full_path)
                fotos.append({
                    "filename": fname,
                    "path": rel_path,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
    fotos.sort(key=lambda f: f["modified_at"], reverse=True)
    return fotos

def fix_encoding(texto: str) -> str:
    if not texto:
        return texto
    reemplazos = {
        "├¡": "í", "Ã­": "í",
        "├®": "é", "Ã©": "é",
        "├│": "ó", "Ã³": "ó",
        "├║": "ú", "Ãº": "ú",
        "Ã¡": "á", "├í": "á",
        "Ã±": "ñ",
        "┬á": " ",
        "┬": "",
        "├▒": "ñ"
    }
    for roto, bien in reemplazos.items():
        texto = texto.replace(roto, bien)
    return texto

def require_admin():
    user_id = get_jwt_identity()
    user = Usuario.query.get(int(user_id))
    if not user or user.rol != "admin":
        return None
    return user

#------------------
#------USER--------
#------------------

#REVISAR-----v

@productos_bp.route("/", methods=["GET"])
def listar_productos():
    try:
        preUrl = os.getenv("URL_BASE_IMG")
        # ------------------------
        # Params
        # ------------------------
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 12))

        min_price = request.args.get("min_price", 0)
        max_price = request.args.get("max_price", 100000)
        en_stock = request.args.get("en_stock", "0")
        sort = request.args.get("sort", "views")

        categorias_param = request.args.get("categoria_ids")  # ej: "1,2,3"

        # ------------------------
        # Query base
        # ------------------------
        query = Producto.query.options(selectinload(Producto.imagenes)).filter(Producto.activo.is_(True))

        # ------------------------
        # Filtro categorías (N:N)
        # ------------------------
        if categorias_param:
            categoria_ids = [int(c) for c in categorias_param.split(",") if c.isdigit()]
            if categoria_ids:
                query = (
                    query
                    .join(Producto.categorias)
                    .filter(Categoria.id.in_(categoria_ids))
                    .distinct()
                )

        # ------------------------
        # Filtro stock
        # ------------------------
        if en_stock == "1":
            query = query.filter(Producto.stock > 0)

        # ------------------------
        # Filtro precio
        # ------------------------
        try:
            min_price = max(0, float(min_price))
            max_price = min(100000, float(max_price))
        except ValueError:
            min_price = 0
            max_price = 100000

        query = query.filter(Producto.precio.between(min_price, max_price))

        # ------------------------
        # Orden
        # ------------------------
        if sort == "price_asc":
            query = query.order_by(Producto.precio.asc())
        elif sort == "price_desc":
            query = query.order_by(Producto.precio.desc())
        elif sort == "rating":
            query = query.order_by(desc(Producto.valoracion_promedio))
        elif sort == "newest":
            query = query.order_by(
                desc(Producto.fecha_creacion),
                desc(Producto.id)
            )
        else:
            query = query.order_by(desc(Producto.vistas))

        # ------------------------
        # Paginado
        # ------------------------
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        productos = pagination.items

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "productos": [
                {
                    "id": p.id,
                    "nombre": p.nombre,
                    "precio": float(p.precio) if p.precio is not None else 0,
                    "extra": p.extra,
                    "url_imagen_principal": (preUrl + p.url_imagen_principal) if p.url_imagen_principal else None,
                    "url_imagen_secundaria": (preUrl + p.imagenes[0].url_imagen) if p.imagenes else None,
                    "stock": p.stock,
                    "vistas": p.vistas,
                    "valoracion_promedio": float(p.valoracion_promedio) if p.valoracion_promedio is not None else 0,
                    "categoria_ids": [c.id for c in (p.categorias or [])],
                }
                for p in productos
            ],
        }), 200

    except Exception:
        current_app.logger.exception("listar_productos failed")
        return jsonify({"error": "Error interno"}), 500

@productos_bp.route("/nombres", methods=["GET"])
def listar_nombres_productos():
    try:
        productos = (
            Producto.query
            .filter(Producto.activo == True)
            .with_entities(Producto.id, Producto.nombre, Producto.url_imagen_principal)
            .all()
        )
        return jsonify([
            {
                "id": p.id,
                "nombre": fix_encoding(p.nombre),
                "url_imagen_principal": p.url_imagen_principal
            } for p in productos
        ])
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@productos_bp.route("/<int:id>", methods=["GET"])
def detalle_producto(id):
    try:
        urlImg = os.getenv("URL_BASE_IMG")
        
        p = Producto.query.options(selectinload(Producto.imagenes)).get(id)

        if not p or not p.activo:
            return jsonify({"msg": "Producto no encontrado"}), 404

        # incrementar vistas sin cargar/rehidratar el objeto (evita commit pesado)
        db.session.query(Producto).filter(Producto.id == p.id).update(
            {Producto.vistas: (Producto.vistas + 1)}, synchronize_session=False
        )
        db.session.commit()

        cat_ids = [c.id for c in (p.categorias or [])]

        sugeridos = []
        if cat_ids:
            sugeridos = (
                Producto.query
                .options(selectinload(Producto.imagenes))
                .join(Producto.categorias)
                .filter(
                    Categoria.id.in_(cat_ids),
                    Producto.id != p.id,
                    Producto.activo.is_(True)
                )
                .distinct()
                .order_by(Producto.vistas.desc(), Producto.valoracion_promedio.desc())
                .limit(8)
                .all()
            )

        sugeridos_data = [
            {
                "id": s.id,
                "precio": s.precio,
                "nombre": s.nombre,
                "extra": s.extra,
                "url_imagen_principal": (urlImg + s.url_imagen_principal) if s.url_imagen_principal else None,
                "url_imagen_secundaria": (urlImg + s.imagenes[0].url_imagen) if s.imagenes else None,
                "categorias": [
                    {"id": c.id, "nombre": c.nombre, "slug": getattr(c, "slug", None)}
                    for c in (s.categorias or [])
                ],
            }
            for s in sugeridos
        ]

        return jsonify({
            "id": p.id,
            "nombre": p.nombre,
            "extra": p.extra,
            "precio": p.precio,
            "peso": p.peso,
            "stock": p.stock,
            "url_imagen_principal": (urlImg + p.url_imagen_principal) if p.url_imagen_principal else None,

            "categorias": [
                {"id": c.id, "nombre": c.nombre, "slug": getattr(c, "slug", None)}
                for c in (p.categorias or [])
            ],

            "slug": p.slug,
            "descripcion_corta": p.descripcion_corta,
            "descripcion_larga": p.descripcion_larga,
            "imagenes": [(urlImg + img.url_imagen) if img.url_imagen else None for img in (p.imagenes or [])],
            "sugeridos": sugeridos_data
        })
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@productos_bp.route("/stock/check", methods=["POST"])
def check_stock():
    try:
        
        data = request.get_json() or {}
        items = data.get("items") or []

        if not isinstance(items, list) or len(items) == 0:
            return jsonify({"ok": False, "error": "items inválido"}), 400

        ids = []
        req_map = {}
        for i in items:
            try:
                pid = int(i.get("id"))
                qty = int(i.get("qty", 1))
                if qty < 1:
                    qty = 1
                ids.append(pid)
                req_map[pid] = qty
            except Exception:
                continue

        productos = Producto.query.filter(Producto.id.in_(ids), Producto.activo.is_(True)).all()
        stock_map = {p.id: int(p.stock or 0) for p in productos}

        issues = []
        for pid in ids:
            requested = int(req_map.get(pid, 1))
            available = int(stock_map.get(pid, 0))
            if requested > available:
                issues.append({"id": pid, "available": available, "requested": requested})

        return jsonify({"ok": len(issues) == 0, "issues": issues}), 200
    
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500
#------------------
#------ADMIN-------
#------------------
#Listar Admin
@productos_bp.route("/admin", methods=["GET"])
@jwt_required()
def listar_productos_admin():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        preUrl = os.getenv("URL_BASE_IMG")
        # ------------------------
        # Params
        # ------------------------
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 12))

        min_price = request.args.get("min_price", 0)
        max_price = request.args.get("max_price", 100000)
        en_stock = request.args.get("en_stock", "0")
        sort = request.args.get("sort", "views")

        categorias_param = request.args.get("categoria_ids")  # ej: "1,2,3"

        # ------------------------
        # Query base
        # ------------------------
        query = Producto.query.options(selectinload(Producto.imagenes))

        # ------------------------
        # Filtro categorías (N:N)
        # ------------------------
        if categorias_param:
            categoria_ids = [int(c) for c in categorias_param.split(",") if c.isdigit()]
            if categoria_ids:
                query = (
                    query
                    .join(Producto.categorias)
                    .filter(Categoria.id.in_(categoria_ids))
                    .distinct()
                )

        # ------------------------
        # Filtro stock
        # ------------------------
        if en_stock == "1":
            query = query.filter(Producto.stock > 0)

        # ------------------------
        # Filtro precio
        # ------------------------
        try:
            min_price = max(0, float(min_price))
            max_price = min(100000, float(max_price))
        except ValueError:
            min_price = 0
            max_price = 100000

        query = query.filter(Producto.precio.between(min_price, max_price))

        # ------------------------
        # Orden
        # ------------------------
        if sort == "price_asc":
            query = query.order_by(Producto.precio.asc())
        elif sort == "price_desc":
            query = query.order_by(Producto.precio.desc())
        elif sort == "rating":
            query = query.order_by(desc(Producto.valoracion_promedio))
        elif sort == "newest":
            query = query.order_by(
                desc(Producto.fecha_creacion),
                desc(Producto.id)
            )
        else:
            query = query.order_by(desc(Producto.vistas))

        # ------------------------
        # Paginado
        # ------------------------
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        productos = pagination.items

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total": pagination.total,
            "pages": pagination.pages,

            # ✅ volvemos a lo que el front espera
            "productos": [
                {
                    "id": p.id,
                    "nombre": p.nombre,
                    "precio": float(p.precio) if p.precio is not None else 0,
                    "extra": p.extra,
                    "url_imagen_principal": (preUrl + p.url_imagen_principal) if p.url_imagen_principal else None,
                    "url_imagen_secundaria": (preUrl + p.imagenes[0].url_imagen) if p.imagenes else None,
                    "stock": p.stock,
                    "vistas": p.vistas,
                    "valoracion_promedio": float(p.valoracion_promedio) if p.valoracion_promedio is not None else 0,
                    "categoria_ids": [c.id for c in (p.categorias or [])],
                }
                for p in productos
            ],

            # (opcional) si querés mantener compat o debug:
            # "filters_applied": {
            #     "categoria_ids": categoria_ids,
            #     "in_stock": in_stock,
            #     "min_price": min_price,
            #     "max_price": max_price,
            #     "sort": sort,
            # }
        }), 200

    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

# Crear producto 
@productos_bp.route("/", methods=["POST"])
@jwt_required()
def crear_producto():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        # Datos del formulario
        nombre = request.form.get("nombre")
        descripcion_corta = request.form.get("descripcion_corta")
        descripcion_larga = request.form.get("descripcion_larga")
        precio = request.form.get("precio", type=float)
        stock = request.form.get("stock", type=int, default=0)
        peso = request.form.get("peso")

        # ✅ NUEVO: extra
        extra = request.form.get("extra")

        # ✅ NUEVO: categoria_ids (CSV: "1,2,3")
        categoria_ids_raw = [int(i) for i in request.form.getlist("categoria_ids") if i]
        
        slug = request.form.get("slug")

        producto = Producto(
            nombre=nombre,
            descripcion_corta=descripcion_corta,
            descripcion_larga=descripcion_larga,
            precio=precio,
            stock=stock,
            peso=peso,
            extra=extra,                
            slug=slug,
            vistas=0,
            valoracion_promedio=0.0
        )

        db.session.add(producto)
        db.session.flush()  # Genera el id del producto sin hacer commit

        # ✅ ASIGNAR CATEGORÍAS N:N
        # Si viene categoria_ids lo usamos; sino fallback a categoria_id (legacy)
        categoria_ids = categoria_ids_raw

        if categoria_ids:
            cats = Categoria.query.filter(Categoria.id.in_(categoria_ids)).all()
            producto.categorias = cats

        # Imagen principal
        if "imagen_principal" in request.files:
            file = request.files["imagen_principal"]
            if file and allowed_file(file.filename) and is_imagen_valida(file):
                year, month, upload_path = get_upload_path()
                base = secure_filename(nombreArchivoBase(producto.nombre, producto.id, "principal"))
                filename = save_imagen_optimizada(file, upload_path, base)
                producto.url_imagen_principal = f"{year}/{month}/{filename}"
            else:
                return jsonify({"msg": "Archivo de imagen principal no permitido"}), 400

        # Archivos
        if "imagenes" in request.files:
            files = request.files.getlist("imagenes")
            for i, file in enumerate(files):
                if file and allowed_file(file.filename) and is_imagen_valida(file):
                    year, month, upload_path = get_upload_path()
                    base = secure_filename(nombreArchivoBase(producto.nombre, producto.id, i))
                    filename = save_imagen_optimizada(file, upload_path, base)
                    producto.imagenes.append(
                        ImagenProducto(url_imagen=f"{year}/{month}/{filename}", fecha_modificacion=now_ar())
                    )
                else:
                    return jsonify({"msg": "Archivo de imagen no permitido"}), 400

        db.session.commit()  # Commit final
        _invalidar_cache_fotos()

        return jsonify({"message": "Producto creado", "id": producto.id}), 201
    except Exception:
        db.session.rollback()
        current_app.logger.exception("productos endpoint failed")
        return jsonify({"error": "Error interno"}), 500

# Actualizar producto (ADMIN)
@productos_bp.route("/<int:id>", methods=["PATCH"])
@jwt_required()
def actualizar_producto(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        producto = Producto.query.get_or_404(id)

        form = request.form

        if "nombre" in form:
            producto.nombre = form.get("nombre")

        if "slug" in form:
            producto.slug = form.get("slug")

        if "descripcion_corta" in form:
            producto.descripcion_corta = form.get("descripcion_corta")

        if "descripcion_larga" in form:
            producto.descripcion_larga = form.get("descripcion_larga")

        if "precio" in form:
            producto.precio = float(form.get("precio"))

        if "stock" in form:
            producto.stock = int(form.get("stock"))

        if "peso" in form:
            producto.peso = float(form.get("peso"))

        if "extra" in form:
            producto.extra = form.get("extra")

        if "fecha_creacion" in form:
            try:
                producto.fecha_creacion = datetime.fromisoformat(form.get("fecha_creacion"))
            except ValueError:
                return jsonify({"error": "Formato de fecha inválido. Usá ISO 8601: YYYY-MM-DDTHH:MM:SS"}), 400

        # ✅ NUEVO: categoria_ids (CSV)
        if "categoria_ids" in form:
            raw = form.get("categoria_ids") or ""
            categoria_ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]

            if categoria_ids:
                cats = Categoria.query.filter(Categoria.id.in_(categoria_ids)).all()
                producto.categorias = cats
            else:
                # si viene vacío, limpiamos categorías
                producto.categorias = []

        # 🖼️ Imagen principal nueva
        if "imagen_principal" in request.files:
            file = request.files["imagen_principal"]
            if file and allowed_file(file.filename) and is_imagen_valida(file):
                year, month, upload_path = get_upload_path()
                base = secure_filename(nombreArchivoBase(producto.nombre, producto.id, "principal"))
                filename = save_imagen_optimizada(file, upload_path, base)
                producto.url_imagen_principal = f"{year}/{month}/{filename}"
            else:
                return jsonify({"msg": "Imagen principal no permitida"}), 400

        # 🖼️ Imágenes secundarias nuevas
        if "imagenes" in request.files:
            files = request.files.getlist("imagenes")
            for i, file in enumerate(files):
                if file and allowed_file(file.filename) and is_imagen_valida(file):
                    year, month, upload_path = get_upload_path()
                    base = secure_filename(nombreArchivoBase(producto.nombre, producto.id, i))
                    filename = save_imagen_optimizada(file, upload_path, base)
                    producto.imagenes.append(
                        ImagenProducto(url_imagen=f"{year}/{month}/{filename}", fecha_modificacion=now_ar())
                    )
                else:
                    return jsonify({"msg": "Imagen secundaria no permitida"}), 400

        db.session.commit()
        _invalidar_cache_fotos()
        return jsonify({
            "message": "Producto actualizado"
        }), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("productos endpoint failed")
        return jsonify({"error": "Error interno"}), 500

@productos_bp.route("/filtro", methods=["GET"])
@jwt_required()
def buscar_por_nombre():
    try:
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Acceso denegado"}), 403
        preUrl = os.getenv("URL_BASE_IMG")

        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))
        filtro = request.args.get("filtro", "")

        min_price = request.args.get("min_price", 0)
        max_price = request.args.get("max_price", 100000)
        en_stock = request.args.get("en_stock", "0")
        sort = request.args.get("sort", "views")

        categorias_param = request.args.get("categoria_ids")  # ej: "1,2,3"

        # Base query
        query = Producto.query.options(selectinload(Producto.imagenes))

        # -----------------------------
        # FILTRO POR NOMBRE
        # -----------------------------
        if filtro:
            filtro_escaped = filtro.replace("%", r"\%").replace("_", r"\_")
            query = query.filter(Producto.nombre.ilike(f"%{filtro_escaped}%"))

        # -----------------------------
        # FILTRO POR CATEGORÍAS (N:N)
        # -----------------------------
        if categorias_param:
            categoria_ids = [int(c) for c in categorias_param.split(",") if c.isdigit()]
            if categoria_ids:
                query = (
                    query
                    .join(Producto.categorias)
                    .filter(Categoria.id.in_(categoria_ids))
                    .distinct()
                )

        # -----------------------------
        # FILTRO STOCK
        # -----------------------------
        if en_stock == "1":
            query = query.filter(Producto.stock > 0)

        # -----------------------------
        # FILTRO PRECIO
        # -----------------------------
        try:
            min_price = max(0, float(min_price))
            max_price = min(100000, float(max_price))
        except ValueError:
            min_price = 0
            max_price = 100000

        query = query.filter(Producto.precio.between(min_price, max_price))

        # -----------------------------
        # ORDEN
        # -----------------------------
        if sort == "price_asc":
            query = query.order_by(Producto.precio.asc())
        elif sort == "price_desc":
            query = query.order_by(Producto.precio.desc())
        elif sort == "rating":
            query = query.order_by(desc(Producto.valoracion_promedio))
        elif sort == "newest":
            query = query.order_by(desc(Producto.fecha_creacion), desc(Producto.id))
        else:
            query = query.order_by(desc(Producto.vistas))

        # -----------------------------
        # PAGINADO
        # -----------------------------
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        productos = pagination.items

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total": pagination.total,
            "pages": pagination.pages,
            "productos": [
                {
                    "id": p.id,
                    "nombre": p.nombre,
                    "precio": float(p.precio) if p.precio is not None else 0,
                    "extra": p.extra,
                    "url_imagen_principal": (preUrl + p.url_imagen_principal) if p.url_imagen_principal else None,
                    "url_imagen_secundaria": (preUrl + p.imagenes[0].url_imagen) if p.imagenes else None,
                    "stock": p.stock,
                    "vistas": p.vistas,
                    "valoracion_promedio": float(p.valoracion_promedio) if p.valoracion_promedio is not None else 0,
                    "categoria_ids": [c.id for c in (p.categorias or [])],
                }
                for p in productos
            ],
        }), 200

    except Exception as e:
        return jsonify({"error": "Error interno"}), 500
    
@productos_bp.route("/admin/<int:id>", methods=["GET"])
@jwt_required()
def detalle_producto_admin(id):
    try:
        admin = require_admin()
        if not admin:
            return jsonify({"error": "Acceso denegado"}), 403
        
        urlImg = os.getenv("URL_BASE_IMG")
        
        p = Producto.query.get(id)

        if not p:
            return jsonify({"msg": "Producto no encontrado"}), 404

        db.session.commit()

        return jsonify({
            "id": p.id,
            "nombre": p.nombre,
            "extra": p.extra,
            "precio": p.precio,
            "peso": p.peso,
            "stock": p.stock,
            "activo": p.activo,
            "url_imagen_principal": (urlImg + p.url_imagen_principal) if p.url_imagen_principal else None,

            "categorias": [
                {"id": c.id, "nombre": c.nombre, "slug": getattr(c, "slug", None)}
                for c in (p.categorias or [])
            ],

            "slug": p.slug,
            "descripcion_corta": p.descripcion_corta,
            "descripcion_larga": p.descripcion_larga,
            "fecha_creacion": p.fecha_creacion.isoformat() if p.fecha_creacion else None,
            "fecha_modificacion": p.fecha_modificacion.isoformat() if p.fecha_modificacion else None,
            "imagenes": [{"id": img.id, "url": (urlImg + img.url_imagen) if img.url_imagen else None} for img in (p.imagenes or [])]
        })
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

# Agregar imagen a producto (ADMIN)
# Form-data: campo "imagen" (archivo) + campo "tipo" = "principal" | "secundaria"
@productos_bp.route("/<int:id>/imagen", methods=["POST"])
@jwt_required()
def agregar_imagen_producto(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        producto = Producto.query.get_or_404(id)

        if "imagen" not in request.files:
            return jsonify({"error": "No se envió ninguna imagen"}), 400

        file = request.files["imagen"]
        if not file or not allowed_file(file.filename) or not is_imagen_valida(file):
            return jsonify({"error": "Archivo no permitido"}), 400

        tipo = request.form.get("tipo", "secundaria")

        year, month, upload_path = get_upload_path()
        indice = "principal" if tipo == "principal" else len(producto.imagenes)
        base = secure_filename(nombreArchivoBase(producto.nombre, producto.id, indice))
        filename = save_imagen_optimizada(file, upload_path, base)
        relative_path = f"{year}/{month}/{filename}"

        urlImg = os.getenv("URL_BASE_IMG")

        if tipo == "principal":
            producto.url_imagen_principal = relative_path
            db.session.commit()
            _invalidar_cache_fotos()
            return jsonify({
                "message": "Imagen principal actualizada",
                "url_imagen_principal": urlImg + relative_path
            }), 200
        else:
            nueva = ImagenProducto(url_imagen=relative_path, fecha_modificacion=now_ar())
            producto.imagenes.append(nueva)
            db.session.commit()
            _invalidar_cache_fotos()
            return jsonify({
                "message": "Imagen agregada",
                "id": nueva.id,
                "url_imagen": urlImg + relative_path
            }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Error interno"}), 500


# Eliminar imagen principal (ADMIN) — solo borra la relación, no el archivo
@productos_bp.route("/<int:id>/imagen/principal", methods=["DELETE"])
@jwt_required()
def eliminar_imagen_principal(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        producto = Producto.query.get_or_404(id)
        producto.url_imagen_principal = None
        db.session.commit()
        return jsonify({"message": "Imagen principal eliminada"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Error interno"}), 500


# Eliminar imagen secundaria (ADMIN) — solo borra la relación, no el archivo
@productos_bp.route("/<int:id>/imagen/<int:imagen_id>", methods=["DELETE"])
@jwt_required()
def eliminar_imagen_secundaria(id, imagen_id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        imagen = ImagenProducto.query.filter_by(id=imagen_id, producto_id=id).first()
        if not imagen:
            return jsonify({"error": "Imagen no encontrada"}), 404
        db.session.delete(imagen)
        db.session.commit()
        return jsonify({"message": "Imagen eliminada"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Error interno"}), 500

@productos_bp.route("/<int:id>/imagen/existente", methods=["POST"])
@jwt_required()
def asociar_imagen_existente(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        producto = Producto.query.get_or_404(id)
        data = request.get_json() or {}
        rel_path = data.get("path", "").replace("\\", "/").lstrip("/")
        tipo = data.get("tipo", "secundaria")

        if not rel_path:
            return jsonify({"error": "Falta el campo 'path'"}), 400

        # Evitar path traversal: el archivo debe quedar dentro de UPLOAD_FOLDER
        base = os.path.realpath(UPLOAD_FOLDER)
        full_path = os.path.realpath(os.path.join(UPLOAD_FOLDER, rel_path))
        if full_path != base and not full_path.startswith(base + os.sep):
            return jsonify({"error": "path inválido"}), 400

        if not os.path.isfile(full_path):
            return jsonify({"error": "El archivo no existe en el servidor"}), 404

        ext = rel_path.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({"error": "Tipo de archivo no permitido"}), 400

        urlImg = os.getenv("URL_BASE_IMG", "")

        if tipo == "principal":
            producto.url_imagen_principal = rel_path
            db.session.commit()
            return jsonify({
                "message": "Imagen principal actualizada",
                "url_imagen_principal": urlImg + rel_path,
            }), 200
        else:
            nueva = ImagenProducto(url_imagen=rel_path, fecha_modificacion=now_ar())
            producto.imagenes.append(nueva)
            db.session.commit()
            return jsonify({
                "message": "Imagen secundaria agregada",
                "id": nueva.id,
                "url_imagen": urlImg + rel_path,
            }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Error interno"}), 500


@productos_bp.route("/admin/fotos", methods=["GET"])
@jwt_required()
def listar_todas_las_fotos():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        preUrl = os.getenv("URL_BASE_IMG", "")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        filtro = request.args.get("nombre", "").lower()

        now = time.time()
        with _fotos_cache_lock:
            cached = _fotos_cache["data"]
            fresh = cached is not None and (now - _fotos_cache["ts"]) < _FOTOS_TTL
            if not fresh:
                cached = _build_fotos_index()
                _fotos_cache["data"] = cached
                _fotos_cache["ts"] = now
            index = cached

        if filtro:
            index = [f for f in index if filtro in f["filename"].lower()]

        total = len(index)
        pages = (total + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page

        fotos = [
            {**f, "url": preUrl + f["path"]}
            for f in index[start:end]
        ]

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": pages,
            "fotos": fotos,
        }), 200
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

# Eliminar producto (ADMIN)
@productos_bp.route("/<int:id>", methods=["DELETE"])
@jwt_required()
def eliminar_producto(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:    
        producto = Producto.query.get_or_404(id)
        producto.activo=False
        db.session.commit()
        return jsonify({"message": "Producto desactivado"}), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("productos endpoint failed")
        return jsonify({"error": "Error interno"}), 500

# Eliminar producto DEFINITIVAMENTE (ADMIN)
@productos_bp.route("/<int:id>/definitivo", methods=["DELETE"])
@jwt_required()
def eliminar_producto_definitivo(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:
        producto = Producto.query.get(id)
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404

        # Si figura en pedidos no se borra: se perdería el historial de ventas
        en_pedidos = PedidoDetalle.query.filter_by(producto_id=id).count()
        if en_pedidos:
            return jsonify({
                "error": f"El producto figura en {en_pedidos} pedido(s) y no se puede eliminar. Desactivalo en su lugar."
            }), 409

        # Dependientes borrados a mano: no se confía en el ON DELETE CASCADE de
        # la base (imagenes usa passive_deletes). Las categorías se desvinculan
        # por la relación. Los archivos en disco se conservan (la galería
        # permite reutilizarlos en otros productos).
        Favorito.query.filter_by(producto_id=id).delete(synchronize_session=False)
        Resena.query.filter_by(producto_id=id).delete(synchronize_session=False)
        ImagenProducto.query.filter_by(producto_id=id).delete(synchronize_session=False)
        nombre = producto.nombre
        db.session.delete(producto)
        db.session.commit()
        current_app.logger.info("Producto eliminado definitivamente id=%s por admin id=%s", id, admin.id)
        return jsonify({"message": f"Producto \"{nombre}\" eliminado definitivamente"}), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("productos endpoint failed")
        return jsonify({"error": "Error interno"}), 500

@productos_bp.route("/activar/<int:id>", methods=["PATCH"])
@jwt_required()
def activar_producto(id):
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    try:    
        producto = Producto.query.get_or_404(id)
        producto.activo=True
        db.session.commit()
        return jsonify({"message": "Producto activado"}), 200
    except Exception:
        db.session.rollback()
        current_app.logger.exception("productos endpoint failed")
        return jsonify({"error": "Error interno"}), 500
    
from sqlalchemy import text
from flask import jsonify

@productos_bp.route("/reparar_textos", methods=["POST"])
@jwt_required()
def reparar_textos():
    admin = require_admin()
    if not admin:
        return jsonify({"error": "Acceso denegado"}), 403
    # Traemos columnas reales
    rows = db.session.execute(text("""
        SELECT id, nombre, descripcion_corta, descripcion_larga, extra
        FROM productos
    """)).mappings().all()

    corregidos = 0
    ids_corregidos = []

    for r in rows:
        pid = r["id"]

        nombre = fix_encoding(r["nombre"])
        corta = fix_encoding(r["descripcion_corta"])
        larga = fix_encoding(r["descripcion_larga"])
        extra = fix_encoding(r["extra"])

        # Solo update si cambió algo (evita writes innecesarios)
        if (nombre != r["nombre"] or corta != r["descripcion_corta"] or
            larga != r["descripcion_larga"] or extra != r["extra"]):

            db.session.execute(text("""
                UPDATE productos
                SET nombre = :nombre,
                    descripcion_corta = :corta,
                    descripcion_larga = :larga,
                    extra = :extra
                WHERE id = :id
            """), {
                "id": pid,
                "nombre": nombre,
                "corta": corta,
                "larga": larga,
                "extra": extra
            })

            corregidos += 1
            ids_corregidos.append(pid)

    db.session.commit()

    return jsonify({
        "productos_corregidos": ids_corregidos,
        "total_corregidos": corregidos
    }), 200
