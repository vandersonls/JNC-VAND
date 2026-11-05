"""Configuração dos testes automáticos do NJC.

Os testes rodam num banco SEPARADO (bmt_teste), recriado do zero a cada
execução a partir do banco/schema.sql. Nunca tocam no banco local "bmt" nem no
banco de produção: o código abaixo se recusa a rodar se o nome do banco não
terminar em "_teste" ou se o servidor não for o MySQL deste computador.

Como rodar (dentro da pasta do projeto):
    bash testar.sh
"""
import os
import re
import subprocess
from pathlib import Path

import mysql.connector
import pytest
from werkzeug.security import generate_password_hash

RAIZ = Path(__file__).resolve().parent.parent

# --- Trava de segurança: só banco de teste, só neste computador ----------
os.environ.pop("MYSQL_URL", None)
os.environ.pop("DATABASE_URL", None)
os.environ["DB_NAME"] = os.environ.get("DB_NAME_TESTE", "bmt_teste")
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ.setdefault("SECRET_KEY", "chave-so-para-testes")

DB_NAME = os.environ["DB_NAME"]
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
if not DB_NAME.endswith("_teste") or DB_HOST not in ("127.0.0.1", "localhost"):
    raise RuntimeError(
        f"Recusando rodar testes em {DB_HOST}/{DB_NAME}: "
        "os testes só rodam num banco local terminado em _teste."
    )

SENHA_MASTER = "Teste1234"
EMAIL_MASTER = "master.teste"


def _conectar(database=None):
    return mysql.connector.connect(
        host=DB_HOST,
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "njc"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=database,
        charset="utf8mb4",
    )


def _recriar_banco():
    """Apaga e recria o banco de teste com o schema.sql do projeto, usando o
    mesmo programa "mysql" do terminal (o schema tem blocos que só ele lê bem)."""
    sql = (RAIZ / "banco" / "schema.sql").read_text(encoding="utf-8")
    sql = re.sub(r"CREATE DATABASE IF NOT EXISTS bmt\b", f"CREATE DATABASE IF NOT EXISTS {DB_NAME}", sql)
    sql = re.sub(r"^USE bmt;", f"USE {DB_NAME};", sql, flags=re.M)
    sql = f"DROP DATABASE IF EXISTS {DB_NAME};\n" + sql
    ambiente = dict(os.environ, MYSQL_PWD=os.environ.get("DB_PASSWORD", ""))
    subprocess.run(
        ["mysql", "-h", DB_HOST, "-P", str(os.environ.get("DB_PORT", 3306)),
         "-u", os.environ.get("DB_USER", "njc")],
        input=sql, text=True, env=ambiente, check=True, stdout=subprocess.DEVNULL,
    )


@pytest.fixture(scope="session")
def app():
    _recriar_banco()
    import app as modulo_app  # importado só depois de configurar o ambiente

    conn = _conectar(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (%s, %s, %s, 'master')",
        ("Master Teste", EMAIL_MASTER, generate_password_hash(SENHA_MASTER)),
    )
    conn.commit()
    conn.close()

    modulo_app.app.config["TESTING"] = True
    return modulo_app.app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logado(client):
    """Cliente já logado como master; sai no fim (o sistema só permite uma
    sessão ativa por usuário)."""
    resp = client.post("/api/login", json={"email": EMAIL_MASTER, "senha": SENHA_MASTER})
    assert resp.status_code == 200, resp.get_json()
    yield client
    client.post("/api/logout")


@pytest.fixture
def banco():
    """Acesso direto ao banco de teste, para conferir o que foi gravado."""
    conn = _conectar(DB_NAME)
    cur = conn.cursor(dictionary=True)

    def consultar(sql, params=()):
        conn.commit()  # enxerga o que o app acabou de gravar
        cur.execute(sql, params)
        if cur.with_rows:
            return cur.fetchall()
        conn.commit()
        return []

    yield consultar
    conn.close()
