import json

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash

import db
from auth import perfis_permitidos
from auditoria import registrar
from areas import areas_permitidas, area_permitida, projeto_permitido, projeto_da_lista, projeto_da_versao_desenho
from versionamento import salvar_versao, obter_rascunho

projetos_bp = Blueprint("projetos", __name__)

# Como o cliente aparece na tela e nos relatórios: o nome fantasia, que é
# por onde ele é conhecido (CBA, Jaguar), caindo na razão social quando não
# houver fantasia. Era `c.razao_social` direto, e no cadastro real há mais de
# um cliente com "NÃO SE APLICA" nessa coluna - quem cadastrou não tinha o
# dado -, então a lista de projetos mostrava "NÃO SE APLICA" no lugar do
# nome do cliente, em linhas diferentes e para clientes diferentes. Dois
# projetos do mesmo cliente continuam podendo existir: nada aqui impede
# repetir cliente, só o `codigo` do projeto é único.
SQL_NOME_CLIENTE = "COALESCE(NULLIF(TRIM(c.nome_fantasia), ''), c.razao_social)"

CAMPOS_PROJETO = ["codigo", "nome", "cliente_id", "descricao", "status"]

# Fase do projeto. É um ENUM no banco: valor fora desta lista não dá erro de
# validação, dá "Data truncated for column 'status'" - ou seja, erro 500 em
# vez de uma mensagem. Por isso a conferência é aqui, antes do INSERT.
STATUS_PROJETO = ("conceitual", "basico", "detalhado")

CAMPOS_CABECALHO_LISTA = (
    "titulo", "subtitulo", "area_titulo", "disciplina",
    "numero_desenho", "numero_cliente", "numero_fornecedor",
    "rev_manual", "data_emissao_manual",
    "elaborador_nome", "elaborador_sigla", "verificador_nome", "verificador_sigla",
    "aprovador_nome", "aprovador_sigla", "autorizado_nome", "autorizado_sigla",
)

# Rev. e Data de emissão são preenchidos à mão (o operador confere com a
# última revisão registrada) - por isso viram NULL quando vazios, em vez de
# string vazia como os demais campos de texto (INT/DATE não aceitam "").
CAMPOS_CABECALHO_NULOS_SE_VAZIO = {"rev_manual", "data_emissao_manual"}

# Tipos de emissão (TE) do carimbo padrão de documentos de engenharia -
# escolhido ao emitir uma versão, usado no histórico de revisões do relatório.
TIPOS_EMISSAO = {
    "A": "PRELIMINAR",
    "B": "PARA APROVAÇÃO",
    "C": "PARA CONHECIMENTO",
    "D": "PARA COTAÇÃO",
    "E": "PARA CONSTRUÇÃO",
    "F": "CONFORME COMPRADO",
    "G": "CONFORME CONSTRUÍDO",
    "H": "CANCELADO",
}


def _sql_update_cabecalho():
    return ", ".join(f"{campo}=%s" for campo in CAMPOS_CABECALHO_LISTA)


def _valores_cabecalho(data, numero_desenho, lista=None):
    """Monta os valores do cabeçalho na ordem de CAMPOS_CABECALHO_LISTA.
    Sem `lista` (criação): campo ausente vira string vazia. Com `lista`
    (edição): campo ausente do payload mantém o valor já salvo."""
    def valor(campo):
        if campo == "numero_desenho":
            bruto = numero_desenho
        elif campo in data:
            bruto = data[campo]
        else:
            bruto = lista[campo] if lista is not None else ""
        if campo in CAMPOS_CABECALHO_NULOS_SE_VAZIO and bruto in ("", None):
            return None
        if campo == "rev_manual" and bruto not in ("", None):
            return int(bruto)
        return bruto
    return tuple(valor(campo) for campo in CAMPOS_CABECALHO_LISTA)


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
        f"""SELECT p.*, {SQL_NOME_CLIENTE} AS cliente_nome, a.nome AS area_nome
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
        f"""SELECT p.*, {SQL_NOME_CLIENTE} AS cliente_nome, c.logo_url AS cliente_logo_url, a.nome AS area_nome
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


def _codigo_automatico(nome):
    """Código do projeto a partir do nome, quando a tela não manda um.

    A coluna `projetos.codigo` é NOT NULL UNIQUE e aparece em nome de
    arquivo de relatório, então não dá simplesmente para deixá-la vazia -
    duas vazias já violariam o índice. O nome do projeto é o que a pessoa
    de fato usa para se referir a ele; o sufixo só entra quando o mesmo
    nome se repete, que é um caso que o aviso de duplicidade já mostrou a
    quem cadastrou."""
    base = (nome or "").strip()[:50] or "projeto"
    candidato = base
    sufixo = 2
    while db.query_one("SELECT id FROM projetos WHERE codigo = %s", (candidato,)):
        corte = 50 - len(f"-{sufixo}")
        candidato = f"{base[:corte]}-{sufixo}"
        sufixo += 1
    return candidato


def _projeto_com_mesmo_nome(cliente_id, nome, ignorar_id=None):
    """Outro projeto do MESMO cliente com o MESMO nome, se houver.

    Repetir não é proibido - o mesmo cliente tem vários projetos, e nada no
    banco impede dois com o mesmo nome. Serve para avisar quem cadastra,
    que é quem sabe se é engano ou não."""
    sql = "SELECT id, codigo, nome FROM projetos WHERE cliente_id = %s AND TRIM(LOWER(nome)) = TRIM(LOWER(%s))"
    params = [cliente_id, nome or ""]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    return db.query_one(sql, tuple(params))


@projetos_bp.post("/api/projetos")
@perfis_permitidos("master", "administrador")
def criar_projeto():
    data = request.get_json(force=True) or {}
    if not data.get("nome") or not data.get("cliente_id") or not data.get("area_id"):
        return jsonify({"erro": "Cliente, nome do projeto e área são obrigatórios"}), 400
    if not area_permitida(int(data["area_id"])):
        return jsonify({"erro": "Você não tem permissão para criar projetos nesta área"}), 403

    # Aviso, não impedimento: só interrompe uma vez, para quem cadastrou
    # decidir. Reenviado com "confirmado", grava igual.
    if not data.get("confirmado"):
        igual = _projeto_com_mesmo_nome(data["cliente_id"], data["nome"])
        if igual:
            return jsonify({
                "erro": f"Cliente já cadastrado com um projeto de mesmo nome ({igual['nome']}).",
                "duplicado": True,
            }), 409

    status = (str(data.get("status") or "conceitual")).strip().lower()
    if status not in STATUS_PROJETO:
        return jsonify({"erro": f"Fase do projeto inválida - use uma de: {', '.join(STATUS_PROJETO)}"}), 400

    codigo = (data.get("codigo") or "").strip() or _codigo_automatico(data["nome"])
    novo_id = db.execute(
        """INSERT INTO projetos (codigo, nome, cliente_id, status, numero_cliente, numero_fornecedor, area_id, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            codigo, data["nome"], data["cliente_id"], status,
            data.get("numero_cliente", ""), data.get("numero_fornecedor", ""), data["area_id"],
            current_user.id,
        ),
    )
    registrar("criar", "projeto", novo_id, f"Criou o projeto {codigo} — {data['nome']}", depois=data)
    return jsonify({"id": novo_id}), 201


@projetos_bp.put("/api/projetos/<int:projeto_id>")
@perfis_permitidos("master", "administrador")
def editar_projeto(projeto_id):
    data = request.get_json(force=True) or {}
    if not data.get("nome") or not data.get("cliente_id") or not data.get("area_id"):
        return jsonify({"erro": "Cliente, nome do projeto e área são obrigatórios"}), 400
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Você não tem permissão para editar este projeto"}), 403
    if not area_permitida(int(data["area_id"])):
        return jsonify({"erro": "Você não tem permissão para mover o projeto para esta área"}), 403
    antes = db.query_one(
        "SELECT codigo, nome, cliente_id, status, numero_cliente, numero_fornecedor, area_id FROM projetos WHERE id = %s",
        (projeto_id,),
    )
    if not antes:
        return jsonify({"erro": "Projeto não encontrado"}), 404

    if not data.get("confirmado"):
        igual = _projeto_com_mesmo_nome(data["cliente_id"], data["nome"], ignorar_id=projeto_id)
        if igual:
            return jsonify({
                "erro": f"Cliente já cadastrado com um projeto de mesmo nome ({igual['nome']}).",
                "duplicado": True,
            }), 409

    # Campos que saíram da tela de cadastro (código, nº do cliente, nº do
    # fornecedor) não vêm mais no corpo. Ausente quer dizer "não mexa",
    # NÃO "apague" - senão editar o nome de um projeto limparia o que já
    # estava gravado e o carimbo das próximas listas nasceria vazio.
    codigo = (data.get("codigo") or "").strip() or antes["codigo"]
    numero_cliente = data.get("numero_cliente", antes["numero_cliente"])
    numero_fornecedor = data.get("numero_fornecedor", antes["numero_fornecedor"])
    status = (str(data.get("status") or antes["status"])).strip().lower()
    if status not in STATUS_PROJETO:
        return jsonify({"erro": f"Fase do projeto inválida - use uma de: {', '.join(STATUS_PROJETO)}"}), 400
    db.execute(
        """UPDATE projetos SET codigo=%s, nome=%s, cliente_id=%s, status=%s,
           numero_cliente=%s, numero_fornecedor=%s, area_id=%s
           WHERE id=%s""",
        (
            codigo, data["nome"], data["cliente_id"], status,
            numero_cliente, numero_fornecedor, data["area_id"],
            projeto_id,
        ),
    )
    registrar("editar", "projeto", projeto_id, f"Editou o projeto {codigo} — {data['nome']}", antes=antes, depois=data)
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


def _extra_campos_emissao(status, data):
    """Ao emitir (status='salvo'), o tipo de emissão (TE, A-H) é obrigatório
    - alimenta o histórico de revisões do relatório. Rascunho não exige.
    Retorna (extra_campos, mensagem_de_erro | None)."""
    if status != "salvo":
        return {}, None
    tipo_emissao = (data.get("tipo_emissao") or "").strip().upper()
    if tipo_emissao not in TIPOS_EMISSAO:
        return None, "Selecione o tipo de emissão (TE) para emitir a versão"
    return {"tipo_emissao": tipo_emissao}, None


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
    extra_campos, erro = _extra_campos_emissao(status, data)
    if erro:
        return jsonify({"erro": erro}), 400

    colunas_cabecalho = ", ".join(CAMPOS_CABECALHO_LISTA)
    placeholders_cabecalho = ", ".join(["%s"] * len(CAMPOS_CABECALHO_LISTA))
    lista_id = db.execute(
        f"INSERT INTO listas_desenho (projeto_id, {colunas_cabecalho}) VALUES (%s, {placeholders_cabecalho})",
        (projeto_id, *_valores_cabecalho(data, numero_desenho)),
    )
    versao_id, numero_versao = salvar_versao(
        "lista_desenho_versoes", "lista_desenho_id", lista_id, status,
        data.get("observacoes", ""), current_user.id, extra_campos=extra_campos,
    )
    _salvar_itens(versao_id, data.get("itens"))
    if status == "salvo":
        db.execute("UPDATE listas_desenho SET versao_atual_id = %s WHERE id = %s", (versao_id, lista_id))
        # Primeira lista emitida do projeto: o carimbo dela passa a ser o
        # padrão da unidade. Rascunho não promove nada - dado de rascunho
        # ainda vai mudar, e o padrão é sticky (não se reescreve sozinho).
        _definir_padrao_na_primeira_lista(projeto_id, lista_id)
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
    extra_campos, erro = _extra_campos_emissao(status, data)
    if erro:
        return jsonify({"erro": erro}), 400

    if any(campo in data for campo in CAMPOS_CABECALHO_LISTA):
        numero_desenho = data.get("numero_desenho", lista["numero_desenho"])
        db.execute(
            f"UPDATE listas_desenho SET {_sql_update_cabecalho()} WHERE id=%s",
            (*_valores_cabecalho(data, numero_desenho, lista=lista), lista_id),
        )

    versao_id, numero_versao = salvar_versao(
        "lista_desenho_versoes", "lista_desenho_id", lista_id, status,
        data.get("observacoes", ""), current_user.id, extra_campos=extra_campos,
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
        f"UPDATE listas_desenho SET {_sql_update_cabecalho()} WHERE id=%s",
        (*_valores_cabecalho(data, numero_desenho), lista_id),
    )
    registrar(
        "editar", "lista_desenho", lista_id,
        f"Editou os dados da pasta da lista {numero_desenho}",
        antes=antes, depois=data,
    )
    return jsonify({"ok": True})


# ---------- Carimbo padrão do projeto ----------
# Montado uma vez, ao preparar o projeto para a unidade, junto com o template
# do cliente. Toda Lista por Desenho criada depois nasce com estes valores já
# preenchidos - o projetista só troca o que é daquela lista (o número do
# desenho, o título, quem elaborou, a data). Antes disto, cada lista era
# digitada do zero: no projeto #10 do banco de teste, a primeira lista tem o
# carimbo inteiro preenchido e as duas seguintes têm tudo NULL.
#
# O número do desenho não entra no padrão: é o que identifica cada lista.
CAMPOS_PADRAO_PROJETO = tuple(c for c in CAMPOS_CABECALHO_LISTA if c != "numero_desenho")

# Rev. e Data de emissão ficam fora do padrão montado pelo sistema: são
# daquela emissão, e herdar data velha é o erro que passa despercebido num
# carimbo. A tela de "Carimbo padrão" ainda aceita gravá-los à mão (projetos
# antigos têm), e o front já os descarta na hora de herdar.
CAMPOS_PADRAO_AUTOMATICO = tuple(c for c in CAMPOS_PADRAO_PROJETO
                                 if c not in CAMPOS_CABECALHO_NULOS_SE_VAZIO)


def _padrao_salvo(projeto_id):
    """Carimbo padrão gravado no projeto, já como dict ({} se não houver,
    None se o projeto não existe). A coluna é JSON e o driver devolve dict,
    texto cru ou bytes, dependendo da versão."""
    row = db.query_one("SELECT cabecalho_padrao FROM projetos WHERE id = %s", (projeto_id,))
    if not row:
        return None
    padrao = row["cabecalho_padrao"]
    if isinstance(padrao, (bytes, bytearray)):
        padrao = padrao.decode("utf-8")
    if isinstance(padrao, str):
        try:
            padrao = json.loads(padrao)
        except ValueError:
            return {}
    return padrao or {}


def _padrao_de_lista(lista):
    """Os campos fixos de uma lista, no formato do carimbo padrão. Campo
    vazio fica de fora: o padrão guarda o que repete, não o que falta."""
    if not lista:
        return {}
    padrao = {}
    for campo in CAMPOS_PADRAO_AUTOMATICO:
        valor = lista.get(campo)
        if isinstance(valor, str):
            valor = valor.strip()
        if valor in (None, ""):
            continue
        padrao[campo] = valor
    return padrao


def _carimbo_da_ultima_lista(projeto_id):
    """Carimbo da lista mais recente DESTE projeto, usado quando o projeto
    ainda não tem padrão gravado - é o caso dos projetos criados antes desta
    regra, que já têm listas preenchidas. Sem isto, a segunda lista de um
    projeto antigo continuaria nascendo vazia. Nunca olha outro projeto: o
    carimbo é da unidade, e misturar unidades é erro grave num documento."""
    colunas = ", ".join(CAMPOS_PADRAO_AUTOMATICO)
    ultima = db.query_one(
        f"SELECT {colunas} FROM listas_desenho WHERE projeto_id = %s ORDER BY id DESC LIMIT 1",
        (projeto_id,),
    )
    return _padrao_de_lista(ultima)


def _definir_padrao_na_primeira_lista(projeto_id, lista_id):
    """A primeira lista do projeto é a que define os dados fixos da unidade:
    o que ela tem de carimbo vira o padrão do projeto, sem ninguém precisar
    abrir a tela de "Carimbo padrão". Daí em diante toda lista nova nasce
    preenchida e o projetista só troca o que é dela (elaborador, verificador,
    o título daquele desenho) - o que ele não mexer fica como está.

    Só grava se o projeto ainda não tiver padrão: um padrão já montado (à mão
    ou pela primeira lista) nunca é sobrescrito por uma lista posterior, para
    o carimbo da unidade não mudar sozinho no meio do projeto."""
    if _padrao_salvo(projeto_id):
        return 0
    colunas = ", ".join(CAMPOS_PADRAO_AUTOMATICO)
    lista = db.query_one(f"SELECT {colunas} FROM listas_desenho WHERE id = %s", (lista_id,))
    padrao = _padrao_de_lista(lista)
    if not padrao:
        return 0
    db.execute(
        "UPDATE projetos SET cabecalho_padrao = %s WHERE id = %s",
        (json.dumps(padrao, ensure_ascii=False), projeto_id),
    )
    registrar(
        "editar", "projeto", projeto_id,
        f"Carimbo padrão do projeto #{projeto_id} montado a partir da lista #{lista_id} "
        f"({len(padrao)} campo(s)) - vale para as próximas listas",
    )
    return len(padrao)


@projetos_bp.get("/api/projetos/<int:projeto_id>/cabecalho-padrao")
@perfis_permitidos("master", "administrador", "projetista")
def obter_cabecalho_padrao(projeto_id):
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para este projeto"}), 403
    padrao = _padrao_salvo(projeto_id)
    if padrao is None:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    # Projeto sem padrão gravado (criado antes desta regra) ainda assim
    # devolve o carimbo da última lista dele - é o mesmo dado fixo, só não
    # tinha sido promovido a padrão.
    return jsonify(padrao or _carimbo_da_ultima_lista(projeto_id))


@projetos_bp.put("/api/projetos/<int:projeto_id>/cabecalho-padrao")
@perfis_permitidos("master", "administrador")
def salvar_cabecalho_padrao(projeto_id):
    if not projeto_permitido(projeto_id):
        return jsonify({"erro": "Sem permissão para este projeto"}), 403
    if not db.query_one("SELECT id FROM projetos WHERE id = %s", (projeto_id,)):
        return jsonify({"erro": "Projeto não encontrado"}), 404
    data = request.get_json(force=True) or {}
    padrao = {}
    for campo in CAMPOS_PADRAO_PROJETO:
        valor = data.get(campo)
        if valor in (None, ""):
            continue
        padrao[campo] = valor
    db.execute(
        "UPDATE projetos SET cabecalho_padrao = %s WHERE id = %s",
        (json.dumps(padrao, ensure_ascii=False) if padrao else None, projeto_id),
    )
    registrar("editar", "projeto", projeto_id,
              f"Salvou o carimbo padrão do projeto #{projeto_id} ({len(padrao)} campo(s))")
    return jsonify({"ok": True, "campos": len(padrao)})


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
