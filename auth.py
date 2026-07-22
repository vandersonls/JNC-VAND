from datetime import datetime, timedelta
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

# Tempo de inatividade após o qual a sessão é encerrada automaticamente
# (e o login em outro local volta a ser permitido). 30 min é o padrão comum
# em sistemas corporativos.
SESSAO_TIMEOUT_MINUTOS = 30

# Proteção contra força bruta: após MAX_TENTATIVAS falhas seguidas, a conta
# fica bloqueada por BLOQUEIO_MINUTOS. Uma janela evita bloqueio permanente.
MAX_TENTATIVAS_LOGIN = 8
BLOQUEIO_MINUTOS = 15


def validar_forca_senha(senha):
    """Retorna None se a senha é aceitável, ou uma mensagem de erro.
    Regra mínima: ao menos 8 caracteres, com letra e número."""
    if not senha or len(senha) < 8:
        return "A senha deve ter ao menos 8 caracteres."
    tem_letra = any(c.isalpha() for c in senha)
    tem_numero = any(c.isdigit() for c in senha)
    if not (tem_letra and tem_numero):
        return "A senha deve conter letras e números."
    return None


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

    # Conta bloqueada por excesso de tentativas?
    if row:
        bloqueado_ate = row.get("login_bloqueado_ate")
        if bloqueado_ate and datetime.now() < bloqueado_ate:
            faltam = int((bloqueado_ate - datetime.now()).total_seconds() // 60) + 1
            return jsonify({"erro": f"Conta temporariamente bloqueada por excesso de tentativas. "
                                    f"Tente novamente em {faltam} minuto(s)."}), 429

    if not row or not check_password_hash(row["senha_hash"], senha):
        # Registra a falha e bloqueia a conta se passar do limite.
        if row:
            falhas = (row.get("login_falhas") or 0) + 1
            if falhas >= MAX_TENTATIVAS_LOGIN:
                db.execute(
                    "UPDATE usuarios SET login_falhas = 0, login_bloqueado_ate = %s WHERE id = %s",
                    (datetime.now() + timedelta(minutes=BLOQUEIO_MINUTOS), row["id"]),
                )
            else:
                db.execute("UPDATE usuarios SET login_falhas = %s WHERE id = %s", (falhas, row["id"]))
        return jsonify({"erro": "Email ou senha inválidos"}), 401

    # Login válido: zera o contador de falhas.
    db.execute("UPDATE usuarios SET login_falhas = 0, login_bloqueado_ate = NULL WHERE id = %s", (row["id"],))

    ultima_atividade = row.get("sessao_ultima_atividade")
    if ultima_atividade and datetime.now() - ultima_atividade < timedelta(minutes=SESSAO_TIMEOUT_MINUTOS):
        return jsonify({
            "erro": "Este usuário já possui uma sessão ativa em outro local. "
                    "Aguarde alguns minutos de inatividade da outra sessão ou saia dela e tente novamente."
        }), 409

    # Sem remember=True: o cookie de sessão expira quando o navegador é
    # fechado, em vez de ficar valido por meses.
    login_user(Usuario(row))
    db.execute("UPDATE usuarios SET sessao_ultima_atividade = NOW() WHERE id = %s", (row["id"],))
    from auditoria import registrar  # import local evita ciclo (auditoria importa perfis_permitidos daqui)
    registrar("login", "usuario", row["id"], f"{row['nome']} entrou no sistema")
    return jsonify({"usuario": Usuario(row).to_dict()})


@auth_bp.post("/api/logout")
@login_required
def logout():
    from auditoria import registrar
    registrar("logout", "usuario", current_user.id, f"{current_user.nome} saiu do sistema")
    db.execute("UPDATE usuarios SET sessao_ultima_atividade = NULL WHERE id = %s", (current_user.id,))
    # logout_user() marca o cookie "lembrar-me" para expirar na resposta;
    # session.clear() depois disso apagaria essa marcação e o cookie nunca seria removido.
    logout_user()
    return jsonify({"ok": True})


def gerenciar_sessao():
    """Chamado antes de cada requisição. Se o usuário estiver inativo há mais
    de SESSAO_TIMEOUT_MINUTOS, encerra a sessão de verdade (não só bloqueia
    login em outro local); caso contrário, renova o horário de atividade."""
    if not current_user.is_authenticated:
        return
    row = db.query_one("SELECT sessao_ultima_atividade FROM usuarios WHERE id = %s", (current_user.id,))
    ultima_atividade = row["sessao_ultima_atividade"] if row else None
    if ultima_atividade and datetime.now() - ultima_atividade > timedelta(minutes=SESSAO_TIMEOUT_MINUTOS):
        logout_user()
        return
    db.execute("UPDATE usuarios SET sessao_ultima_atividade = NOW() WHERE id = %s", (current_user.id,))


@auth_bp.get("/api/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"usuario": None})
    return jsonify({"usuario": current_user.to_dict()})


def hash_senha(senha):
    return generate_password_hash(senha)
