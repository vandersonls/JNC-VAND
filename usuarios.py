from flask import Blueprint, request, jsonify
from flask_login import current_user

import db
from auth import perfis_permitidos, hash_senha

usuarios_bp = Blueprint("usuarios", __name__)


@usuarios_bp.get("/api/usuarios")
@perfis_permitidos("master", "administrador")
def listar_usuarios():
    rows = db.query_all(
        "SELECT id, nome, email, perfil, ativo, criado_em FROM usuarios ORDER BY nome"
    )
    return jsonify(rows)


@usuarios_bp.post("/api/usuarios")
@perfis_permitidos("master")
def criar_usuario():
    data = request.get_json(force=True) or {}
    nome, email, senha = data.get("nome"), (data.get("email") or "").strip().lower(), data.get("senha")
    perfil = data.get("perfil", "visualizador")
    if not nome or not email or not senha:
        return jsonify({"erro": "Nome, email e senha são obrigatórios"}), 400
    if perfil not in ("master", "administrador", "visualizador"):
        return jsonify({"erro": "Perfil inválido"}), 400
    existente = db.query_one("SELECT id FROM usuarios WHERE email = %s", (email,))
    if existente:
        return jsonify({"erro": "Já existe um usuário com este email"}), 409
    novo_id = db.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (%s, %s, %s, %s)",
        (nome, email, hash_senha(senha), perfil),
    )
    return jsonify({"id": novo_id}), 201


@usuarios_bp.put("/api/usuarios/<int:usuario_id>")
@perfis_permitidos("master")
def editar_usuario(usuario_id):
    data = request.get_json(force=True) or {}
    nome, perfil, ativo = data.get("nome"), data.get("perfil"), data.get("ativo", 1)
    if not nome or perfil not in ("master", "administrador", "visualizador"):
        return jsonify({"erro": "Nome e perfil válidos são obrigatórios"}), 400

    if data.get("senha"):
        db.execute(
            "UPDATE usuarios SET nome=%s, perfil=%s, ativo=%s, senha_hash=%s WHERE id=%s",
            (nome, perfil, ativo, hash_senha(data["senha"]), usuario_id),
        )
    else:
        db.execute(
            "UPDATE usuarios SET nome=%s, perfil=%s, ativo=%s WHERE id=%s",
            (nome, perfil, ativo, usuario_id),
        )
    return jsonify({"ok": True})


@usuarios_bp.delete("/api/usuarios/<int:usuario_id>")
@perfis_permitidos("master")
def excluir_usuario(usuario_id):
    if current_user.id == usuario_id:
        return jsonify({"erro": "Você não pode desativar seu próprio usuário"}), 400
    db.execute("UPDATE usuarios SET ativo = 0 WHERE id = %s", (usuario_id,))
    return jsonify({"ok": True})
