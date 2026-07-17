"""Cria o usuário master inicial. Execute uma única vez: python seed.py"""
from werkzeug.security import generate_password_hash

import db
from app import DB_CONFIG

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
