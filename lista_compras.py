from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

import db
from auth import perfis_permitidos
from auditoria import registrar
from areas import projeto_permitido

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
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
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


@lista_compras_bp.post("/api/projetos/<int:projeto_id>/lista-compras/base")
@login_required
def base_lista_compras(projeto_id):
    """Base para uma nova versão da Lista de Compras: a última versão salva
    da Lista PQ do projeto. Se lista_ids for informado, filtra apenas os
    materiais que pertencem à versão atual dessas listas por desenho."""
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
    data = request.get_json(force=True) or {}
    lista_ids = data.get("lista_ids") or []
    projeto = db.query_one("SELECT pq_versao_atual_id FROM projetos WHERE id = %s", (projeto_id,))
    if not projeto or not projeto["pq_versao_atual_id"]:
        return jsonify([])

    filtro_materiais = ""
    params = [projeto["pq_versao_atual_id"]]
    if lista_ids:
        placeholders = ", ".join(["%s"] * len(lista_ids))
        filtro_materiais = f"""AND i.material_id IN (
            SELECT DISTINCT li.material_id
            FROM listas_desenho ld
            JOIN lista_desenho_versoes v ON v.id = ld.versao_atual_id
            JOIN lista_desenho_itens li ON li.versao_id = v.id
            WHERE ld.id IN ({placeholders})
        )"""
        params.extend(lista_ids)

    linhas = db.query_all(
        f"""SELECT i.material_id, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade,
                   i.quantidade_atualizada AS quantidade
            FROM lista_pq_itens i
            JOIN materiais m ON m.id = i.material_id
            WHERE i.versao_id = %s {filtro_materiais}
            ORDER BY m.codigo""",
        tuple(params),
    )
    return jsonify(linhas)


def _carregar_origens_pq_em_lote(pq_versao_ids):
    """Retorna {pq_versao_id: {id, versao, criado_em, origens:[...]}} para
    vários IDs de uma vez (2 consultas no total), em vez de 2 consultas por
    linha (N+1) - usado ao listar várias versões da Lista de Compras."""
    pq_versao_ids = [v for v in pq_versao_ids if v]
    if not pq_versao_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(pq_versao_ids))
    versoes = db.query_all(
        f"SELECT id, versao, criado_em FROM lista_pq_versoes WHERE id IN ({placeholders})",
        tuple(pq_versao_ids),
    )
    origens_rows = db.query_all(
        f"""SELECT pq_versao_id, lista_desenho_id, numero_desenho, titulo, versao_numero
            FROM lista_pq_origens WHERE pq_versao_id IN ({placeholders})
            ORDER BY numero_desenho""",
        tuple(pq_versao_ids),
    )
    origens_por_versao = {}
    for r in origens_rows:
        origens_por_versao.setdefault(r["pq_versao_id"], []).append({
            "lista_desenho_id": r["lista_desenho_id"], "numero_desenho": r["numero_desenho"],
            "titulo": r["titulo"], "versao_numero": r["versao_numero"],
        })
    resultado = {}
    for v in versoes:
        v["origens"] = origens_por_versao.get(v["id"], [])
        resultado[v["id"]] = v
    return resultado


def _carregar_origem_pq(pq_versao_id):
    if not pq_versao_id:
        return None
    return _carregar_origens_pq_em_lote([pq_versao_id]).get(pq_versao_id)


@lista_compras_bp.get("/api/projetos/<int:projeto_id>/lista-compras/versoes")
@login_required
def listar_versoes_compras(projeto_id):
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
    rows = db.query_all(
        """SELECT v.*, u.nome AS criado_por_nome
           FROM lista_compras_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por
           WHERE v.projeto_id = %s ORDER BY v.versao DESC""",
        (projeto_id,),
    )
    origem_pq_por_versao = _carregar_origens_pq_em_lote([r["pq_versao_id"] for r in rows])
    for row in rows:
        row["origem_pq"] = origem_pq_por_versao.get(row["pq_versao_id"])
    return jsonify(rows)


@lista_compras_bp.get("/api/lista-compras/versoes/<int:versao_id>")
@login_required
def obter_versao_compras(versao_id):
    versao = db.query_one("SELECT * FROM lista_compras_versoes WHERE id = %s", (versao_id,))
    if not versao:
        return jsonify({"erro": "Versão não encontrada"}), 404
    if not projeto_permitido(versao["projeto_id"]):
        return jsonify({"erro": "Sem permissão para acessar esta versão"}), 403
    versao["origem_pq"] = _carregar_origem_pq(versao["pq_versao_id"])
    return jsonify({"versao": versao, "itens": _carregar_itens(versao_id)})


@lista_compras_bp.post("/api/projetos/<int:projeto_id>/lista-compras")
@perfis_permitidos("master", "administrador")
def salvar_lista_compras(projeto_id):
    """Sempre cria uma NOVA versão (a anterior nunca é alterada)."""
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para salvar neste projeto"}), 403
    data = request.get_json(force=True) or {}
    itens = data.get("itens") or []
    if not itens:
        return jsonify({"erro": "A Lista de Compras precisa ter pelo menos um item"}), 400

    ultima = db.query_one(
        "SELECT MAX(versao) AS max_versao FROM lista_compras_versoes WHERE projeto_id = %s", (projeto_id,)
    )
    proxima_versao = (ultima["max_versao"] or 0) + 1

    projeto = db.query_one("SELECT pq_versao_atual_id FROM projetos WHERE id = %s", (projeto_id,))
    pq_versao_id = projeto["pq_versao_atual_id"] if projeto else None

    versao_id = db.execute(
        """INSERT INTO lista_compras_versoes (projeto_id, versao, status, observacoes, criado_por, pq_versao_id)
           VALUES (%s, %s, 'salvo', %s, %s, %s)""",
        (projeto_id, proxima_versao, data.get("observacoes", ""), current_user.id, pq_versao_id),
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
