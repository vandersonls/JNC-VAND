import os
from urllib.parse import urlparse

from flask import Flask, render_template
from flask_cors import CORS

import db
from auth import auth_bp, login_manager
from materiais import materiais_bp
from clientes import clientes_bp
from projetos import projetos_bp
from usuarios import usuarios_bp
from configuracoes import config_bp
from auditoria import auditoria_bp
from dashboard import dashboard_bp
from relatorios import relatorios_bp


def _montar_db_config():
    """Usa MYSQL_URL (plugin MySQL do Railway) se existir; senão cai nas variáveis DB_* / defaults locais."""
    url = os.environ.get("MYSQL_URL") or os.environ.get("DATABASE_URL")
    if url:
        p = urlparse(url)
        return {
            "DB_HOST": p.hostname,
            "DB_PORT": p.port or 3306,
            "DB_USER": p.username,
            "DB_PASSWORD": p.password,
            "DB_NAME": p.path.lstrip("/"),
        }
    return {
        "DB_HOST": os.environ.get("DB_HOST") or os.environ.get("MYSQLHOST", "localhost"),
        "DB_PORT": os.environ.get("DB_PORT") or os.environ.get("MYSQLPORT", 3306),
        "DB_USER": os.environ.get("DB_USER") or os.environ.get("MYSQLUSER", "root"),
        "DB_PASSWORD": os.environ.get("DB_PASSWORD") or os.environ.get("MYSQLPASSWORD", "root"),
        "DB_NAME": os.environ.get("DB_NAME") or os.environ.get("MYSQLDATABASE", "bmt"),
    }


DB_CONFIG = _montar_db_config()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
    CORS(app, supports_credentials=True)

    db.init_pool(DB_CONFIG)
    print(f"[NJC] Banco configurado: host={DB_CONFIG['DB_HOST']} port={DB_CONFIG['DB_PORT']} db={DB_CONFIG['DB_NAME']}")

    login_manager.init_app(app)
    login_manager.login_view = None

    app.register_blueprint(auth_bp)
    app.register_blueprint(materiais_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(projetos_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(auditoria_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(relatorios_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
