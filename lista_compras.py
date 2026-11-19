import json

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

import db
from auth import perfis_permitidos
from auditoria import registrar
from areas import projeto_permitido
from projetos import CAMPOS_PADRAO_AUTOMATICO, _padrao_salvo, _carimbo_da_ultima_lista
from versionamento import salvar_versao, obter_rascunho

lista_compras_bp = Blueprint("lista_compras", __name__)


# ---------- Carimbo da Lista de Compras ----------
# A Lista de Compras sai no MESMO template do cliente que a Lista por
# Desenho, com o mesmo carimbo - só que o documento é outro. Por isso o
# carimbo é guardado em cada versão (lista_compras_versoes.cabecalho):
#
# - o que é do projeto (títulos, Nº do cliente, Nº do projetista) vem do
#   carimbo padrão do projeto;
# - o que é deste documento (Nº do documento, título, assinantes) vem da
#   versão anterior da própria Lista de Compras - na primeira, do padrão;
# - Rev. e Data de emissão NUNCA são herdados: são daquela emissão, e data
#   velha num carimbo é o erro que passa despercebido (mesma regra das
#   Listas por Desenho).
CAMPOS_CABECALHO_COMPRAS = (
    "numero_documento", "titulo", "subtitulo", "area_titulo", "disciplina",
    "numero_cliente", "numero_fornecedor", "rev_manual", "data_emissao_manual",
    "elaborador_nome", "elaborador_sigla", "verificador_nome", "verificador_sigla",
    "aprovador_nome", "aprovador_sigla", "autorizado_nome", "autorizado_sigla",
)
CAMPOS_NAO_HERDADOS = ("rev_manual", "data_emissao_manual")

# Título do documento quando ainda não há Lista de Compras: o título do
# padrão é o de uma Lista por Desenho, não serve para este documento.
TITULO_SUGERIDO = "LISTA DE COMPRAS"


def cabecalho_dict(valor):
    """A coluna é JSON e o driver devolve dict, texto cru ou bytes,
    dependendo da versão - aqui sempre vira dict ({} se vazio)."""
    if isinstance(valor, (bytes, bytearray)):
        valor = valor.decode("utf-8")
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return {}
    return valor if isinstance(valor, dict) else {}


def lista_json(valor):
    """Mesmo cuidado de cabecalho_dict, para colunas JSON que guardam lista."""
    if isinstance(valor, (bytes, bytearray)):
        valor = valor.decode("utf-8")
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return []
    return valor if isinstance(valor, list) else []


def _limpar_cabecalho(data):
    """Só os campos conhecidos, sem espaços sobrando e sem os vazios."""
    limpo = {}
    for campo in CAMPOS_CABECALHO_COMPRAS:
        valor = (data or {}).get(campo)
        if isinstance(valor, str):
            valor = valor.strip()
        if valor in (None, ""):
            continue
        limpo[campo] = valor
    return limpo


@lista_compras_bp.get("/api/projetos/<int:projeto_id>/lista-compras/cabecalho-inicial")
@login_required
def cabecalho_inicial_compras(projeto_id):
    """Carimbo com que uma NOVA versão da Lista de Compras abre na tela.
    Devolve também quantos campos vieram preenchidos e de onde, para a tela
    avisar o usuário - igual à Nova Lista por Desenho."""
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
    padrao = _padrao_salvo(projeto_id)
    if padrao is None:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    padrao = padrao or _carimbo_da_ultima_lista(projeto_id)

    anterior = db.query_one(
        """SELECT cabecalho FROM lista_compras_versoes
           WHERE projeto_id = %s AND status = 'salvo' ORDER BY versao DESC LIMIT 1""",
        (projeto_id,),
    )
    cab_anterior = cabecalho_dict(anterior["cabecalho"]) if anterior else {}

    cabecalho = {c: padrao[c] for c in CAMPOS_PADRAO_AUTOMATICO if padrao.get(c) not in (None, "")}
    if cab_anterior:
        cabecalho.update(cab_anterior)
        origem = "da última Lista de Compras emitida"
    else:
        cabecalho["titulo"] = TITULO_SUGERIDO
        origem = "do carimbo padrão do projeto"
    for campo in CAMPOS_NAO_HERDADOS:
        cabecalho.pop(campo, None)
    cabecalho = _limpar_cabecalho(cabecalho)
    return jsonify({"cabecalho": cabecalho, "herdados": len(cabecalho), "origem": origem})


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
        if versao:
            versao["cabecalho"] = cabecalho_dict(versao.get("cabecalho"))
    return jsonify({"versao": versao, "itens": itens})


@lista_compras_bp.post("/api/projetos/<int:projeto_id>/lista-compras/base")
@login_required
def base_lista_compras(projeto_id):
    """Base para uma nova versão da Lista de Compras: a soma, material a
    material, da versão ATUAL (emitida) de cada Lista por Desenho escolhida.

    No processo dos engenheiros cada lista é independente e a Lista de
    Compras pode sair direto das Listas por Desenho - a Planilha de
    Quantidades não é passagem obrigatória (decisão de 2026-11-16). Lista
    que só tem rascunho, sem versão emitida, não entra."""
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
    data = request.get_json(force=True) or {}
    lista_ids = [int(i) for i in (data.get("lista_ids") or [])]
    if not lista_ids:
        return jsonify([])
    placeholders = ", ".join(["%s"] * len(lista_ids))
    linhas = db.query_all(
        f"""SELECT li.material_id, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade,
                   SUM(li.quantidade) AS quantidade
            FROM listas_desenho ld
            JOIN lista_desenho_itens li ON li.versao_id = ld.versao_atual_id
            JOIN materiais m ON m.id = li.material_id
            WHERE ld.projeto_id = %s AND ld.id IN ({placeholders})
            GROUP BY li.material_id, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
            ORDER BY m.codigo""",
        (projeto_id, *lista_ids),
    )
    return jsonify(linhas)


def _origens_das_listas(projeto_id, lista_ids):
    """Retrato das listas usadas, gravado na versão: se a lista mudar
    depois, a Lista de Compras continua dizendo de qual versão dela saiu."""
    if not lista_ids:
        return []
    placeholders = ", ".join(["%s"] * len(lista_ids))
    rows = db.query_all(
        f"""SELECT ld.id AS lista_desenho_id, ld.numero_desenho, ld.titulo, ld.numero_cliente,
                   ld.numero_fornecedor, v.versao AS versao_numero
            FROM listas_desenho ld JOIN lista_desenho_versoes v ON v.id = ld.versao_atual_id
            WHERE ld.projeto_id = %s AND ld.id IN ({placeholders})
            ORDER BY ld.numero_desenho""",
        (projeto_id, *lista_ids),
    )
    return [dict(r) for r in rows]


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
        row["cabecalho"] = cabecalho_dict(row.get("cabecalho"))
        row["listas_origem"] = lista_json(row.get("listas_origem"))
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
    versao["cabecalho"] = cabecalho_dict(versao.get("cabecalho"))
    versao["listas_origem"] = lista_json(versao.get("listas_origem"))
    return jsonify({"versao": versao, "itens": _carregar_itens(versao_id)})


@lista_compras_bp.get("/api/projetos/<int:projeto_id>/lista-compras/rascunho")
@login_required
def obter_rascunho_compras(projeto_id):
    """Rascunho em aberto da Lista de Compras do projeto (se houver), para
    retomar o trabalho de onde parou em vez de recomeçar do zero."""
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para acessar este projeto"}), 403
    versao = obter_rascunho("lista_compras_versoes", "projeto_id", projeto_id)
    if not versao:
        return jsonify({"versao": None, "itens": []})
    versao["cabecalho"] = cabecalho_dict(versao.get("cabecalho"))
    versao["listas_origem"] = lista_json(versao.get("listas_origem"))
    return jsonify({"versao": versao, "itens": _carregar_itens(versao["id"])})


@lista_compras_bp.post("/api/projetos/<int:projeto_id>/lista-compras")
@perfis_permitidos("master", "administrador")
def salvar_lista_compras(projeto_id):
    """Emitida (status='salvo'): cria uma NOVA versão (a anterior nunca é
    alterada). Rascunho: reaproveita o rascunho em aberto, se houver, em vez
    de acumular um a cada pausa no trabalho."""
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para salvar neste projeto"}), 403
    data = request.get_json(force=True) or {}
    itens = data.get("itens") or []
    if not itens:
        return jsonify({"erro": "A Lista de Compras precisa ter pelo menos um item"}), 400
    status = "rascunho" if data.get("status") == "rascunho" else "salvo"
    cabecalho = _limpar_cabecalho(data.get("cabecalho"))
    if status == "salvo" and not cabecalho.get("numero_documento"):
        return jsonify({"erro": "Informe o número do documento da Lista de Compras no carimbo"}), 400

    # Saída direta das Listas por Desenho: a versão guarda de quais listas
    # (e de qual versão de cada uma) saiu. Sem lista informada é o fluxo
    # antigo, a partir da Planilha de Quantidades.
    lista_ids = [int(i) for i in (data.get("lista_ids") or [])]
    origens = _origens_das_listas(projeto_id, lista_ids)
    if origens:
        pq_versao_id = None
    else:
        projeto = db.query_one("SELECT pq_versao_atual_id FROM projetos WHERE id = %s", (projeto_id,))
        pq_versao_id = projeto["pq_versao_atual_id"] if projeto else None

    versao_id, numero_versao = salvar_versao(
        "lista_compras_versoes", "projeto_id", projeto_id, status,
        data.get("observacoes", ""), current_user.id,
        extra_campos={
            "pq_versao_id": pq_versao_id,
            "cabecalho": json.dumps(cabecalho, ensure_ascii=False) if cabecalho else None,
            "listas_origem": json.dumps(origens, ensure_ascii=False, default=str) if origens else None,
        },
    )
    db.execute("DELETE FROM lista_compras_itens WHERE versao_id = %s", (versao_id,))
    for item in itens:
        db.execute(
            """INSERT INTO lista_compras_itens (versao_id, material_id, quantidade, observacao)
               VALUES (%s, %s, %s, %s)""",
            (versao_id, item["material_id"], item.get("quantidade", 0), item.get("observacao", "")),
        )
    if status == "salvo":
        db.execute("UPDATE projetos SET compras_versao_atual_id = %s WHERE id = %s", (versao_id, projeto_id))

    registrar(
        "criar" if status == "salvo" else "rascunho", "lista_compras", projeto_id,
        f"{'Emitiu' if status == 'salvo' else 'Salvou o rascunho d'}a Lista de Compras v{numero_versao} do projeto #{projeto_id}",
        depois=data,
    )
    return jsonify({"versao_id": versao_id, "versao": numero_versao, "status": status}), 201
