import hashlib
import os
from urllib.parse import urlparse

from flask import Flask, render_template

import db
from auth import auth_bp, login_manager, gerenciar_sessao
from materiais import materiais_bp
from clientes import clientes_bp
from projetos import projetos_bp
from usuarios import usuarios_bp
from configuracoes import config_bp
from auditoria import auditoria_bp
from dashboard import dashboard_bp
from relatorios import relatorios_bp
from areas import areas_bp
from lista_pq import lista_pq_bp
from lista_compras import lista_compras_bp


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


def _hash_arquivo(caminho_relativo):
    """Hash do conteúdo do arquivo, usado como ?v= nos links de estático.
    Muda sozinho sempre que o arquivo muda (a cada deploy), forçando o
    navegador a buscar a versão nova em vez de usar uma copiada em cache."""
    caminho = os.path.join(os.path.dirname(__file__), "static", caminho_relativo)
    try:
        with open(caminho, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:10]
    except FileNotFoundError:
        return "0"


ASSET_VERSIONS = {
    "js/app.js": _hash_arquivo("js/app.js"),
    "css/style.css": _hash_arquivo("css/style.css"),
}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
    # Flags de segurança do cookie de sessão:
    #  - Secure: só trafega em HTTPS (Railway serve HTTPS)
    #  - HttpOnly: JavaScript não consegue ler o cookie (mitiga roubo via XSS)
    #  - SameSite=Lax: o cookie não é enviado em requisições cross-site (mitiga CSRF)
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # O app é servido no mesmo domínio da API (SPA same-origin), então NÃO
    # habilitamos CORS - liberar origens cruzadas só aumentaria a superfície
    # de ataque sem necessidade.

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
    app.register_blueprint(areas_bp)
    app.register_blueprint(lista_pq_bp)
    app.register_blueprint(lista_compras_bp)

    @app.before_request
    def verificar_sessao():
        # Roda antes da rota: se a sessão já expirou por inatividade, o
        # usuário é deslogado aqui mesmo, e o @login_required da rota
        # (se houver) já responde 401 corretamente.
        gerenciar_sessao()

    @app.context_processor
    def injetar_versoes_estaticas():
        return {"asset_versions": ASSET_VERSIONS}

    @app.route("/")
    def index():
        resposta = app.make_response(render_template("index.html"))
        # A página principal referencia os arquivos estáticos com ?v=<hash>;
        # se ela mesma ficasse em cache, o navegador nunca veria a URL nova
        # depois de um deploy. Os arquivos JS/CSS (que têm o hash na URL)
        # podem ficar em cache por muito tempo sem esse problema.
        resposta.headers["Cache-Control"] = "no-cache"
        return resposta

    @app.route("/health")
    def health():
        return {"status": "ok"}

    @app.route("/api/versao")
    def versao():
        # Usado pelo frontend pra detectar que um novo deploy saiu enquanto a
        # aba (SPA) segue aberta com o JS antigo, e avisar pra recarregar.
        return {"js": ASSET_VERSIONS["js/app.js"]}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
