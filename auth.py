from functools import wraps

from flask import Blueprint, request, jsonify
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()


class Usuario(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.nome = row["nome"]
        self.email = row["email"]
        self.perfil = row["perfil"]
        self.ativo = row["ativo"]

    def to_dict(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "email": self.email,
            "perfil": self.perfil,
        }


@login_manager.user_loader
def load_user(user_id):
    row = db.query_one("SELECT * FROM usuarios WHERE id = %s AND ativo = 1", (user_id,))
    return Usuario(row) if row else None


@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"erro": "Não autenticado"}), 401


def perfis_permitidos(*perfis):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.perfil not in perfis:
                return jsonify({"erro": "Sem permissão para esta ação"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@auth_bp.post("/api/login")
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    senha = data.get("senha") or ""

    row = db.query_one("SELECT * FROM usuarios WHERE email = %s AND ativo = 1", (email,))
    if not row or not check_password_hash(row["senha_hash"], senha):
        return jsonify({"erro": "Email ou senha inválidos"}), 401

    login_user(Usuario(row), remember=True)
    from auditoria import registrar  # import local evita ciclo (auditoria importa perfis_permitidos daqui)
    registrar("login", "usuario", row["id"], f"{row['nome']} entrou no sistema")
    return jsonify({"usuario": Usuario(row).to_dict()})


@auth_bp.post("/api/logout")
@login_required
def logout():
    from auditoria import registrar
    registrar("logout", "usuario", current_user.id, f"{current_user.nome} saiu do sistema")
    # logout_user() marca o cookie "lembrar-me" para expirar na resposta;
    # session.clear() depois disso apagaria essa marcação e o cookie nunca seria removido.
    logout_user()
    return jsonify({"ok": True})


@auth_bp.get("/api/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"usuario": None})
    return jsonify({"usuario": current_user.to_dict()})


def hash_senha(senha):
    return generate_password_hash(senha)
