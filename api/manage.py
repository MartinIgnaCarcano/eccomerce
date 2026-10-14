from app import app
from database import db
import models  # registra modelos
from flask_migrate import Migrate

migrate = Migrate(app, db)

if __name__ == "__main__":
    app.run()
