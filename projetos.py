from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

import db
from auth import perfis_permitidos
from auditoria import registrar

projetos_bp = Blueprint("projetos", __name__)

CAMPOS_PROJETO = ["codigo", "nome", "cliente_id", "descricao", "status"]


# =========================================================
# PROJETOS
# =========================================================
@projetos_bp.get("/api/projetos")
@login_required
def listar_projetos():
    rows = db.query_all(
        """SELECT p.*, c.razao_social AS cliente_nome
           FROM projetos p
           LEFT JOIN clientes c ON c.id = p.cliente_id
           ORDER BY p.criado_em DESC"""
    )
    return jsonify(rows)


@projetos_bp.get("/api/projetos/<int:projeto_id>")
@login_required
def obter_projeto(projeto_id):
    row = db.query_one(
        """SELECT p.*, c.razao_social AS cliente_nome
           FROM projetos p LEFT JOIN clientes c ON c.id = p.cliente_id
           WHERE p.id = %s""",
        (projeto_id,),
    )
    if not row:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    return jsonify(row)


@projetos_bp.post("/api/projetos")
@perfis_permitidos("master", "administrador")
def criar_projeto():
    data = request.get_json(force=True) or {}
    if not data.get("codigo") or not data.get("nome"):
        return jsonify({"erro": "Código e nome são obrigatórios"}), 400
    novo_id = db.execute(
        """INSERT INTO projetos (codigo, nome, cliente_id, descricao, status, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            data["codigo"], data["nome"], data.get("cliente_id"),
            data.get("descricao", ""), data.get("status", "planejamento"),
            current_user.id,
        ),
    )
    registrar("criar", "projeto", novo_id, f"Criou o projeto {data['codigo']} — {data['nome']}", depois=data)
    return jsonify({"id": novo_id}), 201


@projetos_bp.put("/api/projetos/<int:projeto_id>")
@perfis_permitidos("master", "administrador")
def editar_projeto(projeto_id):
    data = request.get_json(force=True) or {}
    if not data.get("codigo") or not data.get("nome"):
        return jsonify({"erro": "Código e nome são obrigatórios"}), 400
    antes = db.query_one(
        "SELECT codigo, nome, cliente_id, descricao, status FROM projetos WHERE id = %s", (projeto_id,)
    )
    db.execute(
        """UPDATE projetos SET codigo=%s, nome=%s, cliente_id=%s, descricao=%s, status=%s
           WHERE id=%s""",
        (
            data["codigo"], data["nome"], data.get("cliente_id"),
            data.get("descricao", ""), data.get("status", "planejamento"),
            projeto_id,
        ),
    )
    registrar("editar", "projeto", projeto_id, f"Editou o projeto {data['codigo']} — {data['nome']}", antes=antes, depois=data)
    return jsonify({"ok": True})


@projetos_bp.delete("/api/projetos/<int:projeto_id>")
@perfis_permitidos("master")
def excluir_projeto(projeto_id):
    antes = db.query_one("SELECT codigo, nome FROM projetos WHERE id = %s", (projeto_id,))
    db.execute("DELETE FROM projetos WHERE id = %s", (projeto_id,))
    if antes:
        registrar("excluir", "projeto", projeto_id, f"Excluiu o projeto {antes['codigo']} — {antes['nome']}", antes=antes)
    return jsonify({"ok": True})


# =========================================================
# LISTAS POR DESENHO
# =========================================================
@projetos_bp.get("/api/projetos/<int:projeto_id>/listas")
@login_required
def listar_listas(projeto_id):
    rows = db.query_all(
        """SELECT ld.*, v.versao AS versao_atual, v.criado_em AS versao_criado_em
           FROM listas_desenho ld
           LEFT JOIN lista_desenho_versoes v ON v.id = ld.versao_atual_id
           WHERE ld.projeto_id = %s
           ORDER BY ld.numero_desenho""",
        (projeto_id,),
    )
    return jsonify(rows)


def _carregar_itens(versao_id):
    return db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_desenho_itens i
           JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s
           ORDER BY m.codigo""",
        (versao_id,),
    )


@projetos_bp.get("/api/listas/<int:lista_id>")
@login_required
def obter_lista(lista_id):
    lista = db.query_one("SELECT * FROM listas_desenho WHERE id = %s", (lista_id,))
    if not lista:
        return jsonify({"erro": "Lista não encontrada"}), 404
    versao = None
    itens = []
    if lista["versao_atual_id"]:
        versao = db.query_one("SELECT * FROM lista_desenho_versoes WHERE id = %s", (lista["versao_atual_id"],))
        itens = _carregar_itens(lista["versao_atual_id"])
    return jsonify({"lista": lista, "versao": versao, "itens": itens})


@projetos_bp.get("/api/listas/<int:lista_id>/versoes")
@login_required
def listar_versoes(lista_id):
    rows = db.query_all(
        """SELECT v.*, u.nome AS criado_por_nome
           FROM lista_desenho_versoes v
           LEFT JOIN usuarios u ON u.id = v.criado_por
           WHERE v.lista_desenho_id = %s
           ORDER BY v.versao DESC""",
        (lista_id,),
    )
    return jsonify(rows)


@projetos_bp.get("/api/versoes/<int:versao_id>")
@login_required
def obter_versao(versao_id):
    versao = db.query_one("SELECT * FROM lista_desenho_versoes WHERE id = %s", (versao_id,))
    if not versao:
        return jsonify({"erro": "Versão não encontrada"}), 404
    return jsonify({"versao": versao, "itens": _carregar_itens(versao_id)})


def _salvar_itens(versao_id, itens):
    for item in itens or []:
        db.execute(
            """INSERT INTO lista_desenho_itens (versao_id, material_id, quantidade, observacao)
               VALUES (%s, %s, %s, %s)""",
            (versao_id, item["material_id"], item.get("quantidade", 0), item.get("observacao", "")),
        )


@projetos_bp.post("/api/projetos/<int:projeto_id>/listas")
@perfis_permitidos("master", "administrador")
def criar_lista(projeto_id):
    data = request.get_json(force=True) or {}
    numero_desenho = (data.get("numero_desenho") or "").strip()
    if not numero_desenho:
        return jsonify({"erro": "Número do desenho é obrigatório"}), 400

    lista_id = db.execute(
        """INSERT INTO listas_desenho (projeto_id, numero_desenho, titulo)
           VALUES (%s, %s, %s)""",
        (projeto_id, numero_desenho, data.get("titulo", "")),
    )
    versao_id = db.execute(
        """INSERT INTO lista_desenho_versoes (lista_desenho_id, versao, status, observacoes, criado_por)
           VALUES (%s, 1, 'salvo', %s, %s)""",
        (lista_id, data.get("observacoes", ""), current_user.id),
    )
    _salvar_itens(versao_id, data.get("itens"))
    db.execute("UPDATE listas_desenho SET versao_atual_id = %s WHERE id = %s", (versao_id, lista_id))
    registrar(
        "criar", "lista_desenho", lista_id,
        f"Criou a lista por desenho {numero_desenho} (v1) no projeto #{projeto_id}",
        depois=data,
    )
    return jsonify({"id": lista_id, "versao_id": versao_id}), 201


@projetos_bp.put("/api/listas/<int:lista_id>")
@perfis_permitidos("master", "administrador")
def editar_lista(lista_id):
    """Salva uma edição: mantém a versão anterior intacta e cria uma nova versão."""
    data = request.get_json(force=True) or {}
    lista = db.query_one("SELECT * FROM listas_desenho WHERE id = %s", (lista_id,))
    if not lista:
        return jsonify({"erro": "Lista não encontrada"}), 404

    if data.get("titulo") is not None or data.get("numero_desenho"):
        db.execute(
            "UPDATE listas_desenho SET titulo=%s, numero_desenho=%s WHERE id=%s",
            (data.get("titulo", lista["titulo"]), data.get("numero_desenho", lista["numero_desenho"]), lista_id),
        )

    ultima = db.query_one(
        "SELECT MAX(versao) AS max_versao FROM lista_desenho_versoes WHERE lista_desenho_id = %s",
        (lista_id,),
    )
    proxima_versao = (ultima["max_versao"] or 0) + 1

    versao_id = db.execute(
        """INSERT INTO lista_desenho_versoes (lista_desenho_id, versao, status, observacoes, criado_por)
           VALUES (%s, %s, 'salvo', %s, %s)""",
        (lista_id, proxima_versao, data.get("observacoes", ""), current_user.id),
    )
    _salvar_itens(versao_id, data.get("itens"))
    db.execute("UPDATE listas_desenho SET versao_atual_id = %s WHERE id = %s", (versao_id, lista_id))

    registrar(
        "editar", "lista_desenho", lista_id,
        f"Salvou nova versão (v{proxima_versao}) da lista {lista['numero_desenho']}, mantendo as anteriores",
        depois=data,
    )
    return jsonify({"id": lista_id, "versao_id": versao_id, "versao": proxima_versao})


@projetos_bp.delete("/api/listas/<int:lista_id>")
@perfis_permitidos("master", "administrador")
def excluir_lista(lista_id):
    antes = db.query_one("SELECT numero_desenho, titulo FROM listas_desenho WHERE id = %s", (lista_id,))
    db.execute("UPDATE listas_desenho SET versao_atual_id = NULL WHERE id = %s", (lista_id,))
    db.execute("DELETE FROM listas_desenho WHERE id = %s", (lista_id,))
    if antes:
        registrar(
            "excluir", "lista_desenho", lista_id,
            f"Excluiu a lista por desenho {antes['numero_desenho']} e todo o histórico de versões",
            antes=antes,
        )
    return jsonify({"ok": True})
