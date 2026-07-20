from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

import db
from auth import perfis_permitidos
from auditoria import registrar

lista_pq_bp = Blueprint("lista_pq", __name__)


def _carregar_itens(versao_id):
    return db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_pq_itens i
           JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s
           ORDER BY m.codigo""",
        (versao_id,),
    )


@lista_pq_bp.get("/api/projetos/<int:projeto_id>/lista-pq")
@login_required
def obter_lista_pq(projeto_id):
    projeto = db.query_one("SELECT pq_versao_atual_id FROM projetos WHERE id = %s", (projeto_id,))
    if not projeto:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    versao, itens = None, []
    if projeto["pq_versao_atual_id"]:
        versao = db.query_one(
            """SELECT v.*, u.nome AS criado_por_nome FROM lista_pq_versoes v
               LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s""",
            (projeto["pq_versao_atual_id"],),
        )
        itens = _carregar_itens(projeto["pq_versao_atual_id"])
    return jsonify({"versao": versao, "itens": itens})


@lista_pq_bp.get("/api/projetos/<int:projeto_id>/lista-pq/base")
@login_required
def base_lista_pq(projeto_id):
    """Consolida a última versão de CADA Lista por Desenho do projeto (soma
    quantidades por material) - é a base sobre a qual o percentual da Lista PQ
    é aplicado."""
    linhas = db.query_all(
        """SELECT i.material_id, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade,
                  SUM(i.quantidade) AS quantidade_base
           FROM listas_desenho ld
           JOIN lista_desenho_versoes v ON v.id = ld.versao_atual_id
           JOIN lista_desenho_itens i ON i.versao_id = v.id
           JOIN materiais m ON m.id = i.material_id
           WHERE ld.projeto_id = %s
           GROUP BY i.material_id, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           ORDER BY m.codigo""",
        (projeto_id,),
    )
    return jsonify(linhas)


def _carregar_origens(versao_id):
    return db.query_all(
        """SELECT lista_desenho_id, numero_desenho, titulo, versao_numero
           FROM lista_pq_origens WHERE pq_versao_id = %s
           ORDER BY numero_desenho""",
        (versao_id,),
    )


@lista_pq_bp.get("/api/projetos/<int:projeto_id>/lista-pq/versoes")
@login_required
def listar_versoes_pq(projeto_id):
    rows = db.query_all(
        """SELECT v.*, u.nome AS criado_por_nome
           FROM lista_pq_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por
           WHERE v.projeto_id = %s ORDER BY v.versao DESC""",
        (projeto_id,),
    )
    for row in rows:
        row["origens"] = _carregar_origens(row["id"])
    return jsonify(rows)


@lista_pq_bp.get("/api/lista-pq/versoes/<int:versao_id>")
@login_required
def obter_versao_pq(versao_id):
    versao = db.query_one("SELECT * FROM lista_pq_versoes WHERE id = %s", (versao_id,))
    if not versao:
        return jsonify({"erro": "Versão não encontrada"}), 404
    versao["origens"] = _carregar_origens(versao_id)
    return jsonify({"versao": versao, "itens": _carregar_itens(versao_id)})


@lista_pq_bp.post("/api/projetos/<int:projeto_id>/lista-pq")
@perfis_permitidos("master", "administrador")
def salvar_lista_pq(projeto_id):
    """Sempre cria uma NOVA versão (a anterior nunca é alterada)."""
    data = request.get_json(force=True) or {}
    itens = data.get("itens") or []
    if not itens:
        return jsonify({"erro": "A Lista PQ precisa ter pelo menos um item"}), 400

    ultima = db.query_one(
        "SELECT MAX(versao) AS max_versao FROM lista_pq_versoes WHERE projeto_id = %s", (projeto_id,)
    )
    proxima_versao = (ultima["max_versao"] or 0) + 1

    versao_id = db.execute(
        """INSERT INTO lista_pq_versoes (projeto_id, versao, status, observacoes, criado_por)
           VALUES (%s, %s, 'salvo', %s, %s)""",
        (projeto_id, proxima_versao, data.get("observacoes", ""), current_user.id),
    )
    for item in itens:
        quantidade_base = float(item.get("quantidade_base", 0))
        percentual = float(item.get("percentual", 0))
        quantidade_atualizada = item.get("quantidade_atualizada")
        if quantidade_atualizada is None:
            quantidade_atualizada = quantidade_base * (1 + percentual / 100)
        db.execute(
            """INSERT INTO lista_pq_itens (versao_id, material_id, quantidade_base, percentual, quantidade_atualizada, observacao)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (versao_id, item["material_id"], quantidade_base, percentual, quantidade_atualizada, item.get("observacao", "")),
        )
    db.execute("UPDATE projetos SET pq_versao_atual_id = %s WHERE id = %s", (versao_id, projeto_id))

    origens = db.query_all(
        """SELECT ld.id AS lista_desenho_id, ld.numero_desenho, ld.titulo,
                  v.id AS lista_desenho_versao_id, v.versao AS versao_numero
           FROM listas_desenho ld
           JOIN lista_desenho_versoes v ON v.id = ld.versao_atual_id
           WHERE ld.projeto_id = %s""",
        (projeto_id,),
    )
    for origem in origens:
        db.execute(
            """INSERT INTO lista_pq_origens
               (pq_versao_id, lista_desenho_id, lista_desenho_versao_id, numero_desenho, titulo, versao_numero)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (versao_id, origem["lista_desenho_id"], origem["lista_desenho_versao_id"],
             origem["numero_desenho"], origem["titulo"], origem["versao_numero"]),
        )

    registrar(
        "criar", "lista_pq", projeto_id,
        f"Salvou a Lista PQ v{proxima_versao} do projeto #{projeto_id}",
        depois=data,
    )
    return jsonify({"versao_id": versao_id, "versao": proxima_versao}), 201
