from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

import db
from auth import perfis_permitidos
from auditoria import registrar

areas_bp = Blueprint("areas", __name__)


def areas_permitidas(usuario):
    """Retorna None se o usuário enxerga todas as áreas (perfil master),
    ou a lista de IDs de área que ele tem permissão de acessar."""
    if usuario.perfil == "master":
        return None
    rows = db.query_all("SELECT area_id FROM usuario_areas WHERE usuario_id = %s", (usuario.id,))
    return [r["area_id"] for r in rows]


def area_permitida(area_id):
    """True se o usuário logado pode acessar a área informada (master sempre)."""
    permitidas = areas_permitidas(current_user)
    return permitidas is None or (area_id in permitidas)


def projeto_permitido(projeto_id):
    """True se o usuário logado pode acessar o projeto (pela área dele).
    Master sempre pode."""
    permitidas = areas_permitidas(current_user)
    if permitidas is None:
        return True
    row = db.query_one("SELECT area_id FROM projetos WHERE id = %s", (projeto_id,))
    return bool(row) and row["area_id"] in permitidas


def projeto_da_lista(lista_id):
    row = db.query_one("SELECT projeto_id FROM listas_desenho WHERE id = %s", (lista_id,))
    return row["projeto_id"] if row else None


def projeto_da_versao_desenho(versao_id):
    row = db.query_one(
        """SELECT ld.projeto_id FROM lista_desenho_versoes v
           JOIN listas_desenho ld ON ld.id = v.lista_desenho_id WHERE v.id = %s""",
        (versao_id,),
    )
    return row["projeto_id"] if row else None


@areas_bp.get("/api/areas")
@login_required
def listar_areas():
    return jsonify(db.query_all(
        """SELECT a.*, COUNT(m.id) AS total_materiais
           FROM areas a LEFT JOIN materiais m ON m.area_id = a.id AND m.ativo = 1
           GROUP BY a.id ORDER BY a.nome"""
    ))


@areas_bp.post("/api/areas")
@perfis_permitidos("master")
def criar_area():
    data = request.get_json(force=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Nome da área é obrigatório"}), 400
    existente = db.query_one("SELECT id FROM areas WHERE nome = %s", (nome,))
    if existente:
        return jsonify({"erro": "Já existe uma área com este nome"}), 409
    novo_id = db.execute("INSERT INTO areas (nome) VALUES (%s)", (nome,))
    registrar("criar", "area", novo_id, f"Criou a área {nome}", depois={"nome": nome})
    return jsonify({"id": novo_id}), 201


@areas_bp.put("/api/areas/<int:area_id>")
@perfis_permitidos("master")
def editar_area(area_id):
    data = request.get_json(force=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Nome da área é obrigatório"}), 400
    antes = db.query_one("SELECT nome FROM areas WHERE id = %s", (area_id,))
    db.execute("UPDATE areas SET nome = %s WHERE id = %s", (nome, area_id))
    registrar("editar", "area", area_id, f"Renomeou a área para {nome}", antes=antes, depois={"nome": nome})
    return jsonify({"ok": True})


@areas_bp.delete("/api/areas/<int:area_id>")
@perfis_permitidos("master")
def excluir_area(area_id):
    em_uso = db.query_one("SELECT COUNT(*) AS total FROM materiais WHERE area_id = %s AND ativo = 1", (area_id,))
    if em_uso and em_uso["total"] > 0:
        return jsonify({"erro": f"Existem {em_uso['total']} material(is) cadastrados nesta área. Mova-os antes de excluir."}), 400
    antes = db.query_one("SELECT nome FROM areas WHERE id = %s", (area_id,))
    db.execute("DELETE FROM areas WHERE id = %s", (area_id,))
    if antes:
        registrar("excluir", "area", area_id, f"Excluiu a área {antes['nome']}", antes=antes)
    return jsonify({"ok": True})
