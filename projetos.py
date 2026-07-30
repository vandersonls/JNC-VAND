from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash

import db
from auth import perfis_permitidos
from auditoria import registrar
from areas import areas_permitidas, area_permitida, projeto_permitido, projeto_da_lista, projeto_da_versao_desenho
from versionamento import salvar_versao, obter_rascunho

projetos_bp = Blueprint("projetos", __name__)

CAMPOS_PROJETO = ["codigo", "nome", "cliente_id", "descricao", "status"]

CAMPOS_CABECALHO_LISTA = (
    "titulo", "numero_desenho", "numero_cliente", "numero_fornecedor",
    "elaborador_nome", "elaborador_sigla", "verificador_nome", "verificador_sigla",
    "aprovador_nome", "aprovador_sigla",
)


# =========================================================
# PROJETOS
# =========================================================
@projetos_bp.get("/api/projetos")
@login_required
def listar_projetos():
    permitidas = areas_permitidas(current_user)
    filtro, params = "", ()
    if permitidas is not None:
        if not permitidas:
            return jsonify([])  # usuário sem nenhuma área não vê projeto algum
        placeholders = ", ".join(["%s"] * len(permitidas))
        filtro = f"WHERE p.area_id IN ({placeholders})"
        params = tuple(permitidas)
    rows = db.query_all(
        f"""SELECT p.*, c.razao_social AS cliente_nome, a.nome AS area_nome
            FROM projetos p
            LEFT JOIN clientes c ON c.id = p.cliente_id
            LEFT JOIN areas a ON a.id = p.area_id
            {filtro}
            ORDER BY p.criado_em DESC""",
        params,
    )
    return jsonify(rows)


@projetos_bp.get("/api/projetos/<int:projeto_id>")
@login_required
def obter_projeto(projeto_id):
    row = db.query_one(
        """SELECT p.*, c.razao_social AS cliente_nome, c.logo_url AS cliente_logo_url, a.nome AS area_nome
           FROM projetos p
           LEFT JOIN clientes c ON c.id = p.cliente_id
           LEFT JOIN areas a ON a.id = p.area_id
           WHERE p.id = %s""",
        (projeto_id,),
    )
    if not row:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Você não tem permissão para acessar este projeto"}), 403
    return jsonify(row)


@projetos_bp.post("/api/projetos")
@perfis_permitidos("master", "administrador")
def criar_projeto():
    data = request.get_json(force=True) or {}
    if not data.get("codigo") or not data.get("nome") or not data.get("cliente_id") or not data.get("area_id"):
        return jsonify({"erro": "Cliente, nome, código e área são obrigatórios"}), 400
    if not area_permitida(int(data["area_id"])):
        return jsonify({"erro": "Você não tem permissão para criar projetos nesta área"}), 403
    novo_id = db.execute(
        """INSERT INTO projetos (codigo, nome, cliente_id, status, numero_cliente, numero_fornecedor, area_id, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            data["codigo"], data["nome"], data["cliente_id"], data.get("status", "planejamento"),
            data.get("numero_cliente", ""), data.get("numero_fornecedor", ""), data["area_id"],
            current_user.id,
        ),
    )
    registrar("criar", "projeto", novo_id, f"Criou o projeto {data['codigo']} — {data['nome']}", depois=data)
    return jsonify({"id": novo_id}), 201


@projetos_bp.put("/api/projetos/<int:projeto_id>")
@perfis_permitidos("master", "administrador")
def editar_projeto(projeto_id):
    data = request.get_json(force=True) or {}
    if not data.get("codigo") or not data.get("nome") or not data.get("cliente_id") or not data.get("area_id"):
        return jsonify({"erro": "Cliente, nome, código e área são obrigatórios"}), 400
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Você não tem permissão para editar este projeto"}), 403
    if not area_permitida(int(data["area_id"])):
        return jsonify({"erro": "Você não tem permissão para mover o projeto para esta área"}), 403
    antes = db.query_one(
        "SELECT codigo, nome, cliente_id, status, numero_cliente, numero_fornecedor, area_id FROM projetos WHERE id = %s",
        (projeto_id,),
    )
    db.execute(
        """UPDATE projetos SET codigo=%s, nome=%s, cliente_id=%s, status=%s,
           numero_cliente=%s, numero_fornecedor=%s, area_id=%s
           WHERE id=%s""",
        (
            data["codigo"], data["nome"], data["cliente_id"], data.get("status", "planejamento"),
            data.get("numero_cliente", ""), data.get("numero_fornecedor", ""), data["area_id"],
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
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
    rows = db.query_all(
        """SELECT ld.*, v.versao AS versao_atual, v.criado_em AS versao_criado_em,
                  EXISTS(SELECT 1 FROM lista_desenho_versoes r
                         WHERE r.lista_desenho_id = ld.id AND r.status = 'rascunho') AS tem_rascunho
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
    if not projeto_permitido(lista["projeto_id"]):
        return jsonify({"erro": "Sem permissão para acessar esta lista"}), 403
    versao = None
    itens = []
    if lista["versao_atual_id"]:
        versao = db.query_one("SELECT * FROM lista_desenho_versoes WHERE id = %s", (lista["versao_atual_id"],))
        itens = _carregar_itens(lista["versao_atual_id"])
    rascunho = obter_rascunho("lista_desenho_versoes", "lista_desenho_id", lista_id)
    itens_rascunho = _carregar_itens(rascunho["id"]) if rascunho else []
    return jsonify({
        "lista": lista, "versao": versao, "itens": itens,
        "rascunho": rascunho, "itens_rascunho": itens_rascunho,
    })


@projetos_bp.get("/api/listas/<int:lista_id>/versoes")
@login_required
def listar_versoes(lista_id):
    projeto_id = projeto_da_lista(lista_id)
    if projeto_id is None or not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar esta lista"}), 403
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
    versao = db.query_one(
        """SELECT v.*, u.nome AS criado_por_nome FROM lista_desenho_versoes v
           LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s""",
        (versao_id,),
    )
    if not versao:
        return jsonify({"erro": "Versão não encontrada"}), 404
    projeto_id = projeto_da_versao_desenho(versao_id)
    if projeto_id is None or not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar esta versão"}), 403
    lista = db.query_one("SELECT * FROM listas_desenho WHERE id = %s", (versao["lista_desenho_id"],))
    return jsonify({"versao": versao, "itens": _carregar_itens(versao_id), "lista": lista})


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
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para criar listas neste projeto"}), 403
    status = "rascunho" if data.get("status") == "rascunho" else "salvo"

    lista_id = db.execute(
        """INSERT INTO listas_desenho (projeto_id, numero_desenho, titulo, numero_cliente, numero_fornecedor,
                                        elaborador_nome, elaborador_sigla, verificador_nome, verificador_sigla,
                                        aprovador_nome, aprovador_sigla)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            projeto_id, numero_desenho, data.get("titulo", ""), data.get("numero_cliente", ""), data.get("numero_fornecedor", ""),
            data.get("elaborador_nome", ""), data.get("elaborador_sigla", ""),
            data.get("verificador_nome", ""), data.get("verificador_sigla", ""),
            data.get("aprovador_nome", ""), data.get("aprovador_sigla", ""),
        ),
    )
    versao_id, numero_versao = salvar_versao(
        "lista_desenho_versoes", "lista_desenho_id", lista_id, status,
        data.get("observacoes", ""), current_user.id,
    )
    _salvar_itens(versao_id, data.get("itens"))
    if status == "salvo":
        db.execute("UPDATE listas_desenho SET versao_atual_id = %s WHERE id = %s", (versao_id, lista_id))
    registrar(
        "criar", "lista_desenho", lista_id,
        f"Criou a lista por desenho {numero_desenho} (v{numero_versao}{'' if status == 'salvo' else ', rascunho'}) no projeto #{projeto_id}",
        depois=data,
    )
    return jsonify({"id": lista_id, "versao_id": versao_id, "versao": numero_versao, "status": status}), 201


@projetos_bp.put("/api/listas/<int:lista_id>")
@perfis_permitidos("master", "administrador")
def editar_lista(lista_id):
    """Salva uma edição. Emitida (status='salvo'), mantém a versão anterior
    intacta e cria uma nova versão. Rascunho: reaproveita o rascunho em
    aberto (se houver) em vez de acumular um a cada pausa no trabalho."""
    data = request.get_json(force=True) or {}
    lista = db.query_one("SELECT * FROM listas_desenho WHERE id = %s", (lista_id,))
    if not lista:
        return jsonify({"erro": "Lista não encontrada"}), 404
    if not projeto_permitido(lista["projeto_id"]):
        return jsonify({"erro": "Sem permissão para editar esta lista"}), 403
    status = "rascunho" if data.get("status") == "rascunho" else "salvo"

    if any(campo in data for campo in CAMPOS_CABECALHO_LISTA):
        db.execute(
            """UPDATE listas_desenho SET titulo=%s, numero_desenho=%s, numero_cliente=%s, numero_fornecedor=%s,
                                          elaborador_nome=%s, elaborador_sigla=%s, verificador_nome=%s, verificador_sigla=%s,
                                          aprovador_nome=%s, aprovador_sigla=%s
               WHERE id=%s""",
            (
                data.get("titulo", lista["titulo"]), data.get("numero_desenho", lista["numero_desenho"]),
                data.get("numero_cliente", lista["numero_cliente"]), data.get("numero_fornecedor", lista["numero_fornecedor"]),
                data.get("elaborador_nome", lista["elaborador_nome"]), data.get("elaborador_sigla", lista["elaborador_sigla"]),
                data.get("verificador_nome", lista["verificador_nome"]), data.get("verificador_sigla", lista["verificador_sigla"]),
                data.get("aprovador_nome", lista["aprovador_nome"]), data.get("aprovador_sigla", lista["aprovador_sigla"]),
                lista_id,
            ),
        )

    versao_id, numero_versao = salvar_versao(
        "lista_desenho_versoes", "lista_desenho_id", lista_id, status,
        data.get("observacoes", ""), current_user.id,
    )
    db.execute("DELETE FROM lista_desenho_itens WHERE versao_id = %s", (versao_id,))
    _salvar_itens(versao_id, data.get("itens"))
    if status == "salvo":
        db.execute("UPDATE listas_desenho SET versao_atual_id = %s WHERE id = %s", (versao_id, lista_id))

    registrar(
        "editar" if status == "salvo" else "rascunho", "lista_desenho", lista_id,
        f"{'Emitiu' if status == 'salvo' else 'Salvou o rascunho d'}a versão v{numero_versao} da lista {lista['numero_desenho']}",
        depois=data,
    )
    return jsonify({"id": lista_id, "versao_id": versao_id, "versao": numero_versao, "status": status})


@projetos_bp.put("/api/listas/<int:lista_id>/cabecalho")
@perfis_permitidos("master", "administrador")
def editar_cabecalho_lista(lista_id):
    """Atualiza só os dados da pasta (título, cliente/fornecedor, carimbo) -
    não mexe em versões nem itens, ao contrário de editar_lista."""
    data = request.get_json(force=True) or {}
    numero_desenho = (data.get("numero_desenho") or "").strip()
    if not numero_desenho:
        return jsonify({"erro": "Número do desenho é obrigatório"}), 400
    lista = db.query_one("SELECT * FROM listas_desenho WHERE id = %s", (lista_id,))
    if not lista:
        return jsonify({"erro": "Lista não encontrada"}), 404
    if not projeto_permitido(lista["projeto_id"]):
        return jsonify({"erro": "Sem permissão para editar esta lista"}), 403
    antes = {campo: lista[campo] for campo in CAMPOS_CABECALHO_LISTA}
    db.execute(
        """UPDATE listas_desenho SET titulo=%s, numero_desenho=%s, numero_cliente=%s, numero_fornecedor=%s,
                                      elaborador_nome=%s, elaborador_sigla=%s, verificador_nome=%s, verificador_sigla=%s,
                                      aprovador_nome=%s, aprovador_sigla=%s
           WHERE id=%s""",
        (
            data.get("titulo", ""), numero_desenho,
            data.get("numero_cliente", ""), data.get("numero_fornecedor", ""),
            data.get("elaborador_nome", ""), data.get("elaborador_sigla", ""),
            data.get("verificador_nome", ""), data.get("verificador_sigla", ""),
            data.get("aprovador_nome", ""), data.get("aprovador_sigla", ""),
            lista_id,
        ),
    )
    registrar(
        "editar", "lista_desenho", lista_id,
        f"Editou os dados da pasta da lista {numero_desenho}",
        antes=antes, depois=data,
    )
    return jsonify({"ok": True})


@projetos_bp.delete("/api/listas/<int:lista_id>")
@perfis_permitidos("master")
def excluir_lista(lista_id):
    data = request.get_json(silent=True) or {}
    usuario = db.query_one("SELECT senha_hash FROM usuarios WHERE id = %s", (current_user.id,))
    if not usuario or not check_password_hash(usuario["senha_hash"], data.get("senha") or ""):
        return jsonify({"erro": "Senha incorreta"}), 403
    projeto_id = projeto_da_lista(lista_id)
    if projeto_id is None or not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para excluir esta lista"}), 403
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
