from datetime import datetime, timezone, timedelta
from database import db
from werkzeug.security import generate_password_hash, check_password_hash

_AR_TZ = timezone(timedelta(hours=-3))

def now_ar():
    return datetime.now(_AR_TZ).replace(tzinfo=None)

class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=now_ar)
    telefono = db.Column(db.String(20))
    rol = db.Column(db.String(20), nullable=False, default="cliente", server_default="cliente")  # cliente, admin, guest
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    pedidos = db.relationship("Pedido", backref="usuario", lazy=True)
    resenas = db.relationship("Resena", backref="usuario", lazy=True, cascade="all, delete-orphan")
    direccion = db.relationship("Direccion",backref="usuario",uselist=False,cascade="all, delete-orphan")
    favoritos = db.relationship("Favorito", backref="usuario", lazy=True, cascade="all, delete-orphan")
    # Guardar password en hash
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Verificar password
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Direccion(db.Model):
    __tablename__ = "direcciones"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, unique=True)
    calle = db.Column(db.String(150), nullable=False)
    provincia = db.Column(db.String(100), nullable=False)
    codigo_postal = db.Column(db.String(20), nullable=False)
    pais = db.Column(db.String(100), nullable=False)
    extra = db.Column(db.String(200))
    fecha_creacion = db.Column(db.DateTime, default=now_ar)
    departamento = db.Column(db.String(100)) # Opcional  

class Favorito(db.Model):
    __tablename__ = "favoritos"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id", ondelete="CASCADE"), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=now_ar)
    
    producto = db.relationship("Producto", backref="favoritos", lazy=True)

producto_categoria = db.Table(
    "producto_categoria",
    db.Column("producto_id", db.Integer, db.ForeignKey("productos.id", ondelete="CASCADE"), primary_key=True),
    db.Column("categoria_id", db.Integer, db.ForeignKey("categorias.id", ondelete="CASCADE"), primary_key=True),
)

class Categoria(db.Model):
    __tablename__ = "categorias"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    url_imagen = db.Column(db.String(200))
    slug = db.Column(db.String(150), nullable=True) # Nuevo atributo para 'slug'
    icon_key = db.Column(db.String(150), nullable=False)
    
    productos = db.relationship(
        "Producto",
        secondary=producto_categoria,
        back_populates="categorias",
        lazy="selectin",
    )

class Producto(db.Model):
    __tablename__ = "productos"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, index=True)
    activo = db.Column(db.Boolean, default=True, index=True)
    slug = db.Column(db.String(150), unique=True, nullable=False)
    precio = db.Column(db.Numeric(10,2), nullable=False, index=True)
    descripcion_corta = db.Column(db.Text)
    descripcion_larga = db.Column(db.Text)
    stock = db.Column(db.Integer, default=0)
    peso = db.Column(db.Numeric(10,2), default=0.4)
    url_imagen_principal = db.Column(db.String(200))
    extra = db.Column(db.Text)

    fecha_creacion = db.Column(db.DateTime, nullable=True, default=now_ar, index=True)
    fecha_modificacion = db.Column(db.DateTime, nullable=True, onupdate=now_ar)

    vistas = db.Column(db.Integer, default=0, index=True)
    valoracion_promedio = db.Column(db.Numeric(10,2), default=0.0, index=True)
    
    categorias = db.relationship("Categoria", secondary=producto_categoria, back_populates="productos", lazy="selectin")
    imagenes = db.relationship("ImagenProducto", backref="producto", lazy=True, cascade="all, delete-orphan", passive_deletes=True,)
    resenas = db.relationship("Resena", backref="producto", lazy=True)
    detalles_pedido = db.relationship("PedidoDetalle", backref="producto", lazy=True)

class ImagenProducto(db.Model):
    __tablename__ = "imagenes_productos"
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id", ondelete="CASCADE"), nullable=False)
    url_imagen = db.Column(db.String(200), nullable=False)
    fecha_creacion = db.Column(db.DateTime, nullable=True, default=now_ar)
    fecha_modificacion = db.Column(db.DateTime, nullable=True, onupdate=now_ar)

class Pedido(db.Model):
    __tablename__ = "pedidos"
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=now_ar)
    
    # estados: PENDIENTE_PAGO | PAGADO | RECHAZADO | EXPIRADO | ENVIADO | ENTREGADO
    estado = db.Column(db.String(50), default="PENDIENTE_PAGO")
    
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    total = db.Column(db.Numeric(10,2), default=0)
    costo_envio = db.Column(db.Numeric(10,2), default=0)

    # token secreto para que un invitado (sin JWT) pruebe la propiedad del pedido
    # al crear la preferencia de pago
    claim_token = db.Column(db.String(64), nullable=True)

    
    # vencimiento de la reserva
    expires_at = db.Column(db.DateTime, nullable=True)

    # para evitar dobles devoluciones/descuentos
    # reserved | released
    stock_state = db.Column(db.String(20), default="reserved")

    detalles = db.relationship("PedidoDetalle", backref="pedido", lazy=True, passive_deletes=True)

class PedidoDetalle(db.Model):
    __tablename__ = "pedido_detalle"
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id", ondelete="CASCADE"), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    subtotal = db.Column(db.Numeric(10,2), nullable=False)


class Pago(db.Model):
    __tablename__ = "pagos"
    id = db.Column(db.Integer, primary_key=True)

    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)

    # Datos de preferencia de Mercado Pago
    id_preferencia = db.Column(db.String(100), nullable=True, unique=True)
    url_checkout = db.Column(db.String(300), nullable=True)  # init_point para redirigir al checkout
    referencia_externa = db.Column(db.String(100), nullable=True)  # tu referencia interna (ej: número de pedido)

    # Datos del pago real
    id_pago_mp = db.Column(db.String(100), unique=True, nullable=True)  # id de pago que devuelve MP
    id_orden_mercante = db.Column(db.String(100), nullable=True)       # merchant_order_id

    estado = db.Column(db.String(50), nullable=True)         # aprobado, pendiente, rechazado
    detalle_estado = db.Column(db.String(100), nullable=True)  # ej: accredited, cc_rejected_other_reason

    metodo_pago = db.Column(db.String(50), nullable=True)    # ej: visa, master, account_money
    tipo_pago = db.Column(db.String(50), nullable=True)      # ej: credit_card, debit_card, ticket

    monto = db.Column(db.Numeric(10,2), nullable=False)
    moneda = db.Column(db.String(10), default="ARS")

    fecha_creacion = db.Column(db.DateTime, default=now_ar)
    fecha_actualizacion = db.Column(db.DateTime, default=now_ar, onupdate=now_ar)
    
    # ====== Para no mandar mails duplicados ======
    notificado_user = db.Column(db.Boolean, default=False)
    notificado_admin = db.Column(db.Boolean, default=False)
    ultimo_estado_notificado = db.Column(db.String(50), nullable=True)

    pedido = db.relationship("Pedido", backref="pagos", lazy=True)

class Resena(db.Model):
    __tablename__ = "resenas"
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    puntaje = db.Column(db.Integer, nullable=False)
    comentario = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=now_ar)    

class ZonaEnvio(db.Model):
    __tablename__ = "zonas_envio"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False) 
    cp_inicio = db.Column(db.Integer, nullable=False)
    cp_fin = db.Column(db.Integer, nullable=False)

    tipo_envio = db.Column(db.String(50), nullable=False)  # correo | viacargo | andesmar | cata
    precio = db.Column(db.Numeric(10,2), nullable=False)

    activa = db.Column(db.Boolean, default=True)
    
    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "cp_inicio": self.cp_inicio,
            "cp_fin": self.cp_fin,
            "tipo_envio": self.tipo_envio,
            "precio": self.precio,
            "activa": self.activa
        }
