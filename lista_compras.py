from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

import db
from auth import perfis_permitidos
from auditoria import registrar

lista_compras_bp = Blueprint("lista_compras", __name__)


def _carregar_itens(versao_id):
    return db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_compras_itens i
           JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s
           ORDER BY m.codigo""",
        (versao_id,),
    )


@lista_compras_bp.get("/api/projetos/<int:projeto_id>/lista-compras")
@login_required
def obter_lista_compras(projeto_id):
    projeto = db.query_one("SELECT compras_versao_atual_id FROM projetos WHERE id = %s", (projeto_id,))
    if not projeto:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    versao, itens = None, []
    if projeto["compras_versao_atual_id"]:
        versao = db.query_one(
            """SELECT v.*, u.nome AS criado_por_nome FROM lista_compras_versoes v
               LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s""",
            (projeto["compras_versao_atual_id"],),
        )
        itens = _carregar_itens(projeto["compras_versao_atual_id"])
    return jsonify({"versao": versao, "itens": itens})


@lista_compras_bp.get("/api/projetos/<int:projeto_id>/lista-compras/base")
@login_required
def base_lista_compras(projeto_id):
    """Base para uma nova versão da Lista de Compras: a última versão salva
    da Lista PQ do projeto."""
    projeto = db.query_one("SELECT pq_versao_atual_id FROM projetos WHERE id = %s", (projeto_id,))
    if not projeto or not projeto["pq_versao_atual_id"]:
        return jsonify([])
    linhas = db.query_all(
        """SELECT i.material_id, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade,
                  i.quantidade_atualizada AS quantidade
           FROM lista_pq_itens i
           JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s
           ORDER BY m.codigo""",
        (projeto["pq_versao_atual_id"],),
    )
    return jsonify(linhas)


@lista_compras_bp.get("/api/projetos/<int:projeto_id>/lista-compras/versoes")
@login_required
def listar_versoes_compras(projeto_id):
    rows = db.query_all(
        """SELECT v.*, u.nome AS criado_por_nome
           FROM lista_compras_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por
           WHERE v.projeto_id = %s ORDER BY v.versao DESC""",
        (projeto_id,),
    )
    return jsonify(rows)


@lista_compras_bp.get("/api/lista-compras/versoes/<int:versao_id>")
@login_required
def obter_versao_compras(versao_id):
    versao = db.query_one("SELECT * FROM lista_compras_versoes WHERE id = %s", (versao_id,))
    if not versao:
        return jsonify({"erro": "Versão não encontrada"}), 404
    return jsonify({"versao": versao, "itens": _carregar_itens(versao_id)})


@lista_compras_bp.post("/api/projetos/<int:projeto_id>/lista-compras")
@perfis_permitidos("master", "administrador")
def salvar_lista_compras(projeto_id):
    """Sempre cria uma NOVA versão (a anterior nunca é alterada)."""
    data = request.get_json(force=True) or {}
    itens = data.get("itens") or []
    if not itens:
        return jsonify({"erro": "A Lista de Compras precisa ter pelo menos um item"}), 400

    ultima = db.query_one(
        "SELECT MAX(versao) AS max_versao FROM lista_compras_versoes WHERE projeto_id = %s", (projeto_id,)
    )
    proxima_versao = (ultima["max_versao"] or 0) + 1

    versao_id = db.execute(
        """INSERT INTO lista_compras_versoes (projeto_id, versao, status, observacoes, criado_por)
           VALUES (%s, %s, 'salvo', %s, %s)""",
        (projeto_id, proxima_versao, data.get("observacoes", ""), current_user.id),
    )
    for item in itens:
        db.execute(
            """INSERT INTO lista_compras_itens (versao_id, material_id, quantidade, observacao)
               VALUES (%s, %s, %s, %s)""",
            (versao_id, item["material_id"], item.get("quantidade", 0), item.get("observacao", "")),
        )
    db.execute("UPDATE projetos SET compras_versao_atual_id = %s WHERE id = %s", (versao_id, projeto_id))

    registrar(
        "criar", "lista_compras", projeto_id,
        f"Salvou a Lista de Compras v{proxima_versao} do projeto #{projeto_id}",
        depois=data,
    )
    return jsonify({"versao_id": versao_id, "versao": proxima_versao}), 201
