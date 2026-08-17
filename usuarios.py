from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_login import current_user

import db
from auth import perfis_permitidos, hash_senha, validar_forca_senha, SESSAO_TIMEOUT_MINUTOS
from auditoria import registrar

usuarios_bp = Blueprint("usuarios", __name__)


def _definir_areas_usuario(usuario_id, area_ids):
    db.execute("DELETE FROM usuario_areas WHERE usuario_id = %s", (usuario_id,))
    for area_id in set(area_ids or []):
        db.execute("INSERT INTO usuario_areas (usuario_id, area_id) VALUES (%s, %s)", (usuario_id, area_id))


@usuarios_bp.get("/api/usuarios")
@perfis_permitidos("master", "administrador")
def listar_usuarios():
    rows = db.query_all(
        "SELECT id, nome, email, perfil, ativo, criado_em, sessao_ultima_atividade FROM usuarios ORDER BY nome"
    )
    areas_por_usuario = {}
    for r in db.query_all(
        """SELECT ua.usuario_id, a.id AS area_id, a.nome AS area_nome
           FROM usuario_areas ua JOIN areas a ON a.id = ua.area_id"""
    ):
        areas_por_usuario.setdefault(r["usuario_id"], []).append({"id": r["area_id"], "nome": r["area_nome"]})
    limite = datetime.now() - timedelta(minutes=SESSAO_TIMEOUT_MINUTOS)
    for row in rows:
        row["areas"] = areas_por_usuario.get(row["id"], [])
        ultima = row.pop("sessao_ultima_atividade")
        row["sessao_ativa"] = bool(ultima and ultima > limite)
    return jsonify(rows)


@usuarios_bp.post("/api/usuarios/<int:usuario_id>/encerrar-sessao")
@perfis_permitidos("master")
def encerrar_sessao(usuario_id):
    # Força o encerramento de uma sessão "presa" (ex.: a pessoa fechou a aba
    # sem clicar em Sair, e o beacon de fechamento não chegou a tempo por
    # queda de energia/rede) sem precisar esperar os SESSAO_TIMEOUT_MINUTOS.
    usuario = db.query_one("SELECT nome, email FROM usuarios WHERE id = %s", (usuario_id,))
    if not usuario:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    db.execute("UPDATE usuarios SET sessao_ultima_atividade = NULL WHERE id = %s", (usuario_id,))
    registrar("encerrar_sessao", "usuario", usuario_id, f"Encerrou manualmente a sessão de {usuario['email']}")
    return jsonify({"ok": True})


@usuarios_bp.post("/api/usuarios")
@perfis_permitidos("master")
def criar_usuario():
    data = request.get_json(force=True) or {}
    nome, email, senha = data.get("nome"), (data.get("email") or "").strip().lower(), data.get("senha")
    perfil = data.get("perfil", "visualizador")
    areas = data.get("areas") or []
    if not nome or not email or not senha:
        return jsonify({"erro": "Nome, email e senha são obrigatórios"}), 400
    erro_senha = validar_forca_senha(senha)
    if erro_senha:
        return jsonify({"erro": erro_senha}), 400
    if perfil not in ("master", "administrador", "visualizador"):
        return jsonify({"erro": "Perfil inválido"}), 400
    existente = db.query_one("SELECT id FROM usuarios WHERE email = %s", (email,))
    if existente:
        return jsonify({"erro": "Já existe um usuário com este email"}), 409
    novo_id = db.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (%s, %s, %s, %s)",
        (nome, email, hash_senha(senha), perfil),
    )
    if perfil != "master":
        _definir_areas_usuario(novo_id, areas)
    registrar("criar", "usuario", novo_id, f"Criou o usuário {email} (perfil {perfil})",
              depois={"nome": nome, "email": email, "perfil": perfil, "areas": areas})
    return jsonify({"id": novo_id}), 201


@usuarios_bp.put("/api/usuarios/<int:usuario_id>")
@perfis_permitidos("master")
def editar_usuario(usuario_id):
    data = request.get_json(force=True) or {}
    nome, perfil, ativo = data.get("nome"), data.get("perfil"), data.get("ativo", 1)
    areas = data.get("areas") or []
    if not nome or perfil not in ("master", "administrador", "visualizador"):
        return jsonify({"erro": "Nome e perfil válidos são obrigatórios"}), 400
    if current_user.id == usuario_id and not ativo:
        return jsonify({"erro": "Você não pode desativar seu próprio usuário"}), 400
    if data.get("senha"):
        erro_senha = validar_forca_senha(data["senha"])
        if erro_senha:
            return jsonify({"erro": erro_senha}), 400

    antes = db.query_one("SELECT nome, email, perfil, ativo FROM usuarios WHERE id = %s", (usuario_id,))
    senha_alterada = bool(data.get("senha"))

    if senha_alterada:
        db.execute(
            "UPDATE usuarios SET nome=%s, perfil=%s, ativo=%s, senha_hash=%s WHERE id=%s",
            (nome, perfil, ativo, hash_senha(data["senha"]), usuario_id),
        )
    else:
        db.execute(
            "UPDATE usuarios SET nome=%s, perfil=%s, ativo=%s WHERE id=%s",
            (nome, perfil, ativo, usuario_id),
        )

    if perfil == "master":
        _definir_areas_usuario(usuario_id, [])
    else:
        _definir_areas_usuario(usuario_id, areas)

    descricao = f"Editou o usuário {antes['email'] if antes else usuario_id}"
    if senha_alterada:
        descricao += " (senha redefinida)"
    registrar(
        "editar", "usuario", usuario_id, descricao,
        antes=antes, depois={"nome": nome, "perfil": perfil, "ativo": ativo, "senha_alterada": senha_alterada, "areas": areas},
    )
    return jsonify({"ok": True})


@usuarios_bp.delete("/api/usuarios/<int:usuario_id>")
@perfis_permitidos("master")
def excluir_usuario(usuario_id):
    if current_user.id == usuario_id:
        return jsonify({"erro": "Você não pode desativar seu próprio usuário"}), 400
    antes = db.query_one("SELECT nome, email FROM usuarios WHERE id = %s", (usuario_id,))
    db.execute("UPDATE usuarios SET ativo = 0 WHERE id = %s", (usuario_id,))
    if antes:
        registrar("excluir", "usuario", usuario_id, f"Desativou o usuário {antes['email']}", antes=antes)
    return jsonify({"ok": True})


@usuarios_bp.delete("/api/usuarios/<int:usuario_id>/permanente")
@perfis_permitidos("master")
def excluir_usuario_permanente(usuario_id):
    # Exclusão de verdade (não só desativar). Projetos/listas/versões criados
    # pela pessoa continuam existindo (o schema usa ON DELETE SET NULL nesses
    # casos), e o histórico de auditoria mantém o nome dela por extenso
    # (usuario_nome), então nada se perde além do próprio cadastro de login.
    if current_user.id == usuario_id:
        return jsonify({"erro": "Você não pode excluir seu próprio usuário"}), 400
    antes = db.query_one("SELECT nome, email, perfil FROM usuarios WHERE id = %s", (usuario_id,))
    if not antes:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    db.execute("DELETE FROM usuarios WHERE id = %s", (usuario_id,))
    registrar("excluir", "usuario", usuario_id, f"Excluiu permanentemente o usuário {antes['email']}", antes=antes)
    return jsonify({"ok": True})
