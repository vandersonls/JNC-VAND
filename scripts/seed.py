"""Cria o usuário master inicial no banco LOCAL. Execute uma única vez:
    .venv/bin/python scripts/seed.py
(com as variáveis do banco carregadas: source .njc_local.env)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # raiz do projeto

from werkzeug.security import generate_password_hash  # noqa: E402

import db  # noqa: E402
from app import DB_CONFIG  # noqa: E402

db.init_pool(DB_CONFIG)

EMAIL = "admin@bmt.com"
SENHA = "admin123"

existente = db.query_one("SELECT id FROM usuarios WHERE email = %s", (EMAIL,))
if existente:
    print(f"Usuário master já existe (id={existente['id']}).")
else:
    novo_id = db.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (%s, %s, %s, 'master')",
        ("Administrador", EMAIL, generate_password_hash(SENHA)),
    )
    print(f"Usuário master criado (id={novo_id}). Login: {EMAIL} / Senha: {SENHA}")
    print("IMPORTANTE: troque a senha após o primeiro login.")
