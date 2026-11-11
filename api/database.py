# Logs y print() a logs/app.log. Se activa acá porque database es lo primero
# que importa app.py: cPanel regenera passenger_wsgi.py y app.py no se toca.
from logging_setup import configurar_logs
configurar_logs()

from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()
