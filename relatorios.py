import datetime
import io
import ipaddress
import json
import re
import socket
import urllib.request
from copy import copy
from urllib.parse import urlparse

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image as PdfImage

import db
import log_erros
from areas import projeto_permitido, projeto_da_lista
from projetos import SQL_NOME_CLIENTE, TIPOS_EMISSAO

relatorios_bp = Blueprint("relatorios", __name__)


def _url_segura_para_baixar(url):
    """Proteção contra SSRF: só permite http/https apontando para endereços
    públicos. Bloqueia esquemas perigosos (file://, etc.) e qualquer host que
    resolva para IP interno/privado (loopback, rede local, metadados da nuvem)."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    porta = p.port or (443 if p.scheme == "https" else 80)
    try:
        enderecos = socket.getaddrinfo(p.hostname, porta)
    except Exception:
        return False
    for info in enderecos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _baixar_imagem(url):
    """Baixa uma imagem de logo por URL. Nunca lança exceção - um link de
    logo quebrado, lento ou não permitido não pode impedir a geração do
    relatório. Limita o tamanho lido para não estourar a memória do servidor."""
    if not url or not _url_segura_para_baixar(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read(5 * 1024 * 1024)  # no máximo 5 MB (logo real é bem menor)
    except Exception:
        return None


def _cabecalho_pdf_com_logos(empresa_nome, empresa_logo_url, cliente_nome, cliente_logo_url,
                              projeto_nome, nome_aba, revisao, data_texto):
    """Monta o bloco de cabeçalho padrão (empresa+logo | cliente+logo, depois
    projeto/aba/revisão) usado nos relatórios de Lista por Desenho, Lista PQ
    e Lista de Compras."""
    estilo_nome = ParagraphStyle("cab_nome", fontSize=10, fontName="Helvetica-Bold", alignment=1)
    estilo_rotulo = ParagraphStyle("cab_rotulo", fontSize=7.5, textColor=colors.grey, alignment=1)

    def _celula_logo(nome, url, rotulo):
        img_bytes = _baixar_imagem(url)
        partes = [Paragraph(rotulo, estilo_rotulo)]
        if img_bytes:
            try:
                img = PdfImage(io.BytesIO(img_bytes), width=2.6 * cm, height=2.6 * cm, kind="proportional")
                img.hAlign = "CENTER"
                partes.append(img)
            except Exception:
                pass
        partes.append(Paragraph(nome or "-", estilo_nome))
        return partes

    tabela_logos = Table(
        [[_celula_logo(empresa_nome, empresa_logo_url, "EMPRESA"), _celula_logo(cliente_nome, cliente_logo_url, "CLIENTE")]],
        colWidths=[13.5 * cm, 13.5 * cm],
    )
    tabela_logos.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    titulo_estilo = ParagraphStyle("titulo", fontSize=15, leading=18, alignment=1, spaceAfter=4,
                                    spaceBefore=10, fontName="Helvetica-Bold")
    subtitulo_estilo = ParagraphStyle("subtitulo", fontSize=11, leading=14, alignment=1, spaceAfter=4, fontName="Helvetica-Bold")
    ref_estilo = ParagraphStyle("ref", fontSize=9, leading=12, alignment=1, spaceAfter=10)

    return [
        tabela_logos,
        Paragraph(projeto_nome, titulo_estilo),
        Paragraph(nome_aba, subtitulo_estilo),
        Paragraph(f"Revisão: {revisao} &nbsp;&nbsp;|&nbsp;&nbsp; Data: {data_texto}", ref_estilo),
    ]


def _cabecalho_excel_com_logos(ws, largura_total, empresa_nome, empresa_logo_url, cliente_nome, cliente_logo_url,
                                projeto_nome, nome_aba, revisao, data_texto, linha_inicial=1):
    """Escreve o cabeçalho padrão (com logos, se disponíveis) numa planilha
    e devolve a próxima linha livre."""
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    linha = linha_inicial

    ws.row_dimensions[linha].height = 48
    for offset, (nome, url, rotulo) in enumerate([
        (empresa_nome, empresa_logo_url, "EMPRESA"), (cliente_nome, cliente_logo_url, "CLIENTE"),
    ]):
        col_ini = 1 + offset * (largura_total // 2)
        col_fim = col_ini + (largura_total // 2) - 1
        ws.merge_cells(start_row=linha, start_column=col_ini, end_row=linha, end_column=col_fim)
        cel = ws.cell(row=linha, column=col_ini, value=f"{rotulo}: {nome or '-'}")
        cel.font, cel.alignment = Font(bold=True, size=10), centro
        img_bytes = _baixar_imagem(url)
        if img_bytes:
            try:
                img = ExcelImage(io.BytesIO(img_bytes))
                img.width, img.height = 60, 60
                ws.add_image(img, f"{get_column_letter(col_ini)}{linha}")
            except Exception:
                pass
    linha += 1

    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
    cel = ws.cell(row=linha, column=1, value=projeto_nome)
    cel.font, cel.alignment = Font(bold=True, size=13), centro
    linha += 1

    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
    cel = ws.cell(row=linha, column=1, value=nome_aba)
    cel.font, cel.alignment = Font(bold=True, size=10), centro
    linha += 1

    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
    cel = ws.cell(row=linha, column=1, value=f"Revisão: {revisao}    |    Data: {data_texto}")
    cel.font, cel.alignment = Font(size=9), centro
    linha += 2
    return linha

CEL_ESTILO = ParagraphStyle("cel", fontSize=8, leading=10)
CEL_ESTILO_CABECALHO = ParagraphStyle("cel_cab", fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")


def _tabela_quebravel(dados, col_widths, alinhar_direita=None, cor_cabecalho=None, cor_texto_cabecalho=None):
    """Monta uma Table do reportlab em que toda célula é um Paragraph,
    para que o texto quebre linha dentro da largura da coluna em vez de
    transbordar/sobrepor o texto vizinho."""
    alinhar_direita = alinhar_direita or set()
    cor_cabecalho = cor_cabecalho or colors.HexColor("#1f3a5f")
    estilo_cabecalho = (
        CEL_ESTILO_CABECALHO if cor_texto_cabecalho is None
        else ParagraphStyle("cel_cab_custom", fontSize=8, leading=10, textColor=cor_texto_cabecalho, fontName="Helvetica-Bold")
    )
    linhas = []
    for i, linha in enumerate(dados):
        estilo = estilo_cabecalho if i == 0 else CEL_ESTILO
        linhas.append([Paragraph(str(v), estilo) for v in linha])
    tabela = Table(linhas, colWidths=col_widths, repeatRows=1)
    estilo_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), cor_cabecalho),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for col in alinhar_direita:
        estilo_cmds.append(("ALIGN", (col, 0), (col, -1), "CENTER"))
    tabela.setStyle(TableStyle(estilo_cmds))
    return tabela


def _carregar_contexto(lista_id, versao_id=None):
    lista = db.query_one(
        f"""SELECT ld.*, p.codigo AS projeto_codigo, p.nome AS projeto_nome, p.cliente_id AS projeto_cliente_id,
                  {SQL_NOME_CLIENTE} AS cliente_nome, c.logo_url AS cliente_logo_url
           FROM listas_desenho ld
           JOIN projetos p ON p.id = ld.projeto_id
           LEFT JOIN clientes c ON c.id = p.cliente_id
           WHERE ld.id = %s""",
        (lista_id,),
    )
    if not lista:
        return None

    alvo_versao_id = versao_id or lista["versao_atual_id"]
    if not alvo_versao_id:
        return {"lista": lista, "versao": None, "itens": [], "historico": []}

    versao = db.query_one(
        """SELECT v.*, u.nome AS criado_por_nome FROM lista_desenho_versoes v
           LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s""",
        (alvo_versao_id,),
    )
    itens = db.query_all(
        """SELECT i.material_id, i.quantidade, i.observacao, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_desenho_itens i JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s ORDER BY m.codigo""",
        (alvo_versao_id,),
    )
    historico = db.query_all(
        """SELECT v.versao, v.status, v.tipo_emissao, v.observacoes, v.criado_em, u.nome AS criado_por_nome
           FROM lista_desenho_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por
           WHERE v.lista_desenho_id = %s ORDER BY v.versao""",
        (lista_id,),
    )
    config = {c["chave"]: c["valor"] for c in db.query_all("SELECT chave, valor FROM configuracoes")}

    qtd_anterior_por_material = _quantidades_versao_anterior(lista_id, versao)
    for item in itens:
        item["quantidade_anterior"] = qtd_anterior_por_material.get(item["material_id"], 0)

    return {"lista": lista, "versao": versao, "itens": itens, "historico": historico, "config": config}


def _quantidades_versao_anterior(lista_id, versao_atual):
    """Quantidade de cada material na última versão EMITIDA anterior à
    atual (por número de revisão) - usada na coluna QUANT. ANTERIOR do
    relatório, pra mostrar de imediato o que mudou de uma revisão pra outra."""
    if not versao_atual:
        return {}
    anterior = db.query_one(
        """SELECT id FROM lista_desenho_versoes
           WHERE lista_desenho_id = %s AND status = 'salvo' AND versao < %s
           ORDER BY versao DESC LIMIT 1""",
        (lista_id, versao_atual["versao"]),
    )
    if not anterior:
        return {}
    linhas = db.query_all(
        "SELECT material_id, quantidade FROM lista_desenho_itens WHERE versao_id = %s",
        (anterior["id"],),
    )
    return {l["material_id"]: l["quantidade"] for l in linhas}


def _doc_referencia(lista):
    return f"{lista['projeto_codigo']}-{lista['numero_desenho']}"


def _carregar_contexto_projeto(projeto_id):
    """Reúne, para cada Lista por Desenho do projeto, sempre a sua última versão salva."""
    if not projeto_permitido(projeto_id):
        return None
    projeto = db.query_one(
        f"""SELECT p.*, {SQL_NOME_CLIENTE} AS cliente_nome
           FROM projetos p LEFT JOIN clientes c ON c.id = p.cliente_id
           WHERE p.id = %s""",
        (projeto_id,),
    )
    if not projeto:
        return None

    listas = db.query_all(
        "SELECT * FROM listas_desenho WHERE projeto_id = %s ORDER BY numero_desenho",
        (projeto_id,),
    )

    desenhos = []
    consolidado = {}
    for lista in listas:
        versao, itens = None, []
        if lista["versao_atual_id"]:
            versao = db.query_one(
                """SELECT v.*, u.nome AS criado_por_nome FROM lista_desenho_versoes v
                   LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s""",
                (lista["versao_atual_id"],),
            )
            itens = db.query_all(
                """SELECT i.quantidade, i.observacao, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
                   FROM lista_desenho_itens i JOIN materiais m ON m.id = i.material_id
                   WHERE i.versao_id = %s ORDER BY m.codigo""",
                (lista["versao_atual_id"],),
            )
        desenhos.append({"lista": lista, "versao": versao, "itens": itens})

        for item in itens:
            chave = item["codigo"]
            if chave not in consolidado:
                consolidado[chave] = {
                    "codigo": item["codigo"], "descricao": item["descricao"], "fabricante": item["fabricante"],
                    "bitola": item["bitola"], "unidade": item["unidade"], "quantidade": 0, "desenhos": set(),
                }
            consolidado[chave]["quantidade"] += float(item["quantidade"])
            consolidado[chave]["desenhos"].add(lista["numero_desenho"])

    consolidado_lista = sorted(consolidado.values(), key=lambda x: x["codigo"])
    config = {c["chave"]: c["valor"] for c in db.query_all("SELECT chave, valor FROM configuracoes")}

    return {"projeto": projeto, "desenhos": desenhos, "consolidado": consolidado_lista, "config": config}


def _assinatura_curta(lista, campo_nome, campo_sigla):
    """Sigla se houver, senão o nome completo, senão traço - usado nas
    colunas estreitas (Por/Ver./Apr./Aut.) do histórico de revisões."""
    return lista.get(campo_sigla) or lista.get(campo_nome) or "-"


def _rev_exibicao(lista, versao):
    """Rev. preenchida à mão no cabeçalho tem prioridade (o operador confere
    com a última revisão registrada); sem isso, cai no número de versão
    automático do sistema."""
    if lista.get("rev_manual") is not None:
        return lista["rev_manual"]
    return versao["versao"] if versao else "-"


def _data_emissao_exibicao(lista, versao):
    """Mesma lógica da Rev.: data preenchida à mão tem prioridade (permite
    retroagir a data de documentos migrados), senão usa a data real de
    criação da versão no sistema."""
    manual = lista.get("data_emissao_manual")
    if manual:
        return manual.strftime("%d/%m/%Y") if hasattr(manual, "strftime") else str(manual)
    return versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"


# =========================================================
# LISTA POR DESENHO - preenchimento do template exato do cliente
# =========================================================
# Cada cliente manda o próprio template de Excel (upload em Lista por
# Desenho -> Template), com layout próprio, e mapeia uma vez onde cada campo nosso
# vai (tela de mapeamento). O motor abaixo é genérico - só sabe escrever
# "este campo vai nesta célula" e "esta tabela repete a partir desta linha",
# conforme o JSON de mapeamento salvo; não tem nenhuma coordenada de cliente
# específico fixa no código.


def _titulo_aba_valido(texto):
    """Nome de aba do Excel não aceita : \\ / ? * [ ] nem mais de 31 caracteres."""
    texto = re.sub(r'[:\\/?*\[\]]', "-", texto or "")
    return texto[:31] or "Lista"


def _duplicar_linha_estilo(ws, linha_origem, linha_destino, colunas):
    """Copia formatação (fonte/borda/preenchimento/alinhamento) e mesclagens
    de uma linha do template pra uma linha nova - usado quando a lista tem mais
    itens/revisões do que as linhas já prontas no arquivo do cliente."""
    ws.row_dimensions[linha_destino].height = ws.row_dimensions[linha_origem].height
    for _, col_ini, col_fim in colunas:
        for col in range(col_ini, col_fim + 1):
            origem = ws.cell(row=linha_origem, column=col)
            destino = ws.cell(row=linha_destino, column=col)
            destino.font = copy(origem.font)
            destino.border = copy(origem.border)
            destino.fill = copy(origem.fill)
            destino.alignment = copy(origem.alignment)
            destino.number_format = origem.number_format
        if col_fim > col_ini:
            ws.merge_cells(start_row=linha_destino, start_column=col_ini, end_row=linha_destino, end_column=col_fim)


def _escrever_linha_grade(ws, linha, colunas, valores):
    for nome, col_ini, _ in colunas:
        if nome not in valores:
            continue
        cel = ws.cell(row=linha, column=col_ini)
        if isinstance(cel, MergedCell):
            # A coordenada mapeada caiu numa célula que faz parte de uma
            # mesclagem, mas não é a âncora (canto superior esquerdo) - o
            # openpyxl não deixa escrever aí (gerava 500 em vez de só pular
            # esse campo, como já fazemos pra qualquer outro sem valor).
            continue
        cel.value = valores[nome]


def _definir_com_quebra(ws, coord, valor, tamanho_min=9, limite_caracteres=40):
    """Escreve o valor mantendo o resto do estilo da célula, mas ligando
    quebra de linha automática - o template costuma vir sem isso, então texto
    mais longo que o esperado (ex.: nome de projeto grande) vazava pra fora
    da caixa em vez de quebrar dentro dela. Se mesmo quebrando o texto for
    comprido demais, reduz um pouco a fonte em vez de deixar cortado."""
    cel = ws[coord]
    if isinstance(cel, MergedCell):
        # Mesmo motivo do guard em _escrever_linha_grade - célula mapeada é
        # parte de uma mesclagem, não a âncora. Pula em vez de travar.
        return
    if _tem_formula(cel):
        # Célula calculada pelo próprio template do cliente. Escrever aqui
        # apaga a fórmula - e com ela a conferência que o cliente faz
        # (decisão de 2026-10-26). Medido no template Jaguar, cujo
        # mapeamento salvo aponta campos de carimbo para células com
        # `='Capa '!B4`: com o campo vazio, a fórmula virava célula em
        # branco; com valor, virava texto fixo. Em ambos os casos o
        # espelhamento do cliente se perdia no arquivo entregue.
        return
    cel.value = valor
    alin = cel.alignment
    cel.alignment = Alignment(horizontal=alin.horizontal, vertical=alin.vertical, wrap_text=True)
    if tamanho_min is not None and valor and len(str(valor)) > limite_caracteres:
        fonte = cel.font
        novo_tamanho = max(tamanho_min, fonte.size - 2)
        cel.font = Font(name=fonte.name, size=novo_tamanho, bold=fonte.bold, italic=fonte.italic, color=fonte.color)


def _preencher_campos(ws, campos, valores, reservadas=()):
    """campos: {nome_campo: "coordenada"} do mapeamento salvo. valores: dados
    de verdade (lista, versão etc.) já resolvidos. Campo mapeado sem valor
    disponível, ou valor sem campo mapeado, é simplesmente ignorado.

    `reservadas` são as células que o bloco de títulos já ocupou nesta aba.
    Um campo do bloco apontado para lá seria escrito duas vezes - foi o que
    aconteceu no template Jaguar, onde o mapeamento manda `titulo` para B7 e
    o bloco começa em B4: o título saía em duas alturas do carimbo."""
    for campo, coord in campos.items():
        if campo not in valores:
            continue
        if campo in ORDEM_BLOCO_TITULOS and coord in reservadas:
            continue
        _definir_com_quebra(ws, coord, valores[campo])


# ---------------------------------------------------------------------------
# BLOCO DE TÍTULOS DO CARIMBO
#
# Todo template de cliente visto até aqui traz o rótulo "TÍTULO:" e, logo
# abaixo dele, as linhas do carimbo. O que muda de um para outro é a FORMA:
#
#   CBA        rótulo em B6 (negrito), bloco em B7, UMA célula mesclada de
#              B7 até J9, com 4 linhas de texto separadas por quebra;
#   26512      rótulo em C5 (sem negrito), bloco em C6, mesclada C6:G8, 3 linhas;
#   Jaguar     rótulo em B3 (sem negrito), uma célula POR linha: B4, B5, B6...
#
# Daí as regras abaixo, que valem para qualquer template novo sem ninguém
# mapear nada: acha o rótulo, olha a célula de baixo, e escreve conforme ela
# seja um bloco de várias linhas ou uma linha por célula. O negrito não entra
# como condição - dois dos quatro templates não têm.
# ---------------------------------------------------------------------------

# Ordem em que os campos do cadastro caem no bloco, de cima para baixo. É a
# mesma ordem que a tela de cadastro anuncia ("linha 1 do carimbo" ...).
# Campo não preenchido não deixa buraco: os que vierem sobem.
ORDEM_BLOCO_TITULOS = ("subtitulo", "area", "disciplina", "titulo")

MAX_LINHAS_BLOCO = len(ORDEM_BLOCO_TITULOS)


def _eh_rotulo_titulo(valor):
    """"TÍTULO", "TÍTULO:", "Titulo do documento:" - sim. Um texto longo que
    por acaso contém a palavra - não: aí é conteúdo, não rótulo."""
    if not isinstance(valor, str):
        return False
    texto = valor.strip()
    if not texto:
        return False
    sem_acento = (texto.replace("Í", "I").replace("í", "i")
                      .replace("Ú", "U").replace("ú", "u").lower())
    if "titulo" not in sem_acento:
        return False
    return texto.endswith(":") or len(texto) <= 20


def _tem_formula(cel):
    return isinstance(cel.value, str) and cel.value.startswith("=")


def _faixa_mesclada(ws, coordenada):
    for faixa in ws.merged_cells.ranges:
        if coordenada in faixa:
            return faixa
    return None


def _ancora_e_altura(ws, linha, coluna):
    """Devolve (célula onde dá para escrever, quantas linhas ela ocupa).

    Numa mesclagem só a âncora (canto superior esquerdo) aceita valor; as
    outras são MergedCell e estouram ao receber escrita - foi o que já
    gerou 500 antes."""
    cel = ws.cell(row=linha, column=coluna)
    faixa = _faixa_mesclada(ws, cel.coordinate)
    if faixa is None:
        return cel, 1
    return ws.cell(row=faixa.min_row, column=faixa.min_col), faixa.max_row - faixa.min_row + 1


def _eh_limite_do_bloco(cel):
    """Onde o espaço do bloco acaba: o rótulo do campo seguinte, ou uma
    célula com fórmula (que se preenche sozinha e não pode ser apagada)."""
    if _tem_formula(cel):
        return True
    return isinstance(cel.value, str) and cel.value.strip().endswith(":")


def _escrever_bloco(ws, linha_rotulo, coluna, linhas_texto):
    """Escreve as linhas do carimbo logo abaixo do rótulo.

    Devolve o conjunto de coordenadas que o bloco ocupa (escritas ou
    reservadas), para o preenchimento por mapeamento não repetir conteúdo
    ali. Conjunto vazio quer dizer que não dava para escrever."""
    destino, altura = _ancora_e_altura(ws, linha_rotulo + 1, coluna)
    if _tem_formula(destino):
        # A célula se preenche sozinha a partir de outra aba (é o caso da
        # aba de lista do template Jaguar, que espelha a capa). Escrever
        # aqui apagaria a fórmula do cliente - decisão de 2026-10-26.
        return set()

    if altura > 1:
        # Bloco de várias linhas numa célula só: vira um texto com quebras.
        destino.value = "\n".join(linhas_texto)
        alin = destino.alignment
        destino.alignment = Alignment(horizontal=alin.horizontal, vertical=alin.vertical, wrap_text=True)
        faixa = _faixa_mesclada(ws, destino.coordinate)
        if faixa is None:
            return {destino.coordinate}
        return {c.coordinate for linha in ws[faixa.coord] for c in linha}

    # Uma célula por linha, descendo a partir da primeira. A região fica
    # reservada até onde o bloco caberia (não só até onde foi escrito):
    # quem preencheu 2 dos 4 campos não deve ver o resto do carimbo
    # repetido logo abaixo por um campo mapeado.
    ocupadas = set()
    linha = linha_rotulo + 1
    restantes = list(linhas_texto)
    for _ in range(MAX_LINHAS_BLOCO):
        cel, passo = _ancora_e_altura(ws, linha, coluna)
        if _eh_limite_do_bloco(cel):
            break
        ocupadas.add(cel.coordinate)
        if restantes:
            cel.value = restantes.pop(0)
            alin = cel.alignment
            cel.alignment = Alignment(horizontal=alin.horizontal, vertical=alin.vertical, wrap_text=True)
        linha += passo
    return ocupadas


def _preencher_blocos_de_titulo(ws, valores):
    """Preenche TODAS as ocorrências do bloco de títulos desta aba.

    São várias de propósito: na aba "Lista de materiais" da CBA o carimbo se
    repete a cada folha (linhas 6, 50, 94, 138 e 182). Preencher só a
    primeira deixaria as folhas seguintes com "TÍTULO DO PROJETO" escrito ao
    pé da letra."""
    linhas_texto = [str(valores[c]).strip() for c in ORDEM_BLOCO_TITULOS
                    if str(valores.get(c, "") or "").strip()]
    if not linhas_texto:
        # Ninguém preencheu nenhum dos campos: não há o que escrever, e
        # apagar o texto de exemplo do cliente não é tarefa nossa.
        return set()

    # Os rótulos são colhidos antes de escrever: escrever dentro do laço
    # mudaria a planilha que ele está percorrendo.
    rotulos = [(cel.row, cel.column) for linha in ws.iter_rows() for cel in linha
               if not isinstance(cel, MergedCell) and _eh_rotulo_titulo(cel.value)]

    ocupadas = set()
    for linha_rotulo, coluna in rotulos:
        ocupadas |= _escrever_bloco(ws, linha_rotulo, coluna, linhas_texto[:MAX_LINHAS_BLOCO])
    return ocupadas


def _descricao_com_complemento(tabela_cfg, colunas, linhas_dados):
    """Junta a bitola à descrição quando o template do cliente não tem coluna
    para ela.

    No cadastro, materiais de uma mesma família têm a MESMA descrição e se
    distinguem pela bitola: `GE-01-01` a `GE-01-06` são todos "ABRAÇADEIRA DE
    UNIÃO HORIZONTAL PARA ELETRODUTOS...", mudando só 1/2", 1", 1.1/4"...
    O template da CBA tem Código, Descrição, Unidade e Quantidade - não tem
    coluna de bitola. Sem esta junção, a lista sai com cinco linhas de
    descrição idêntica e códigos diferentes, e quem lê não consegue dizer
    qual é qual (constatado em 2026-11-15, lista 56).

    Só age quando a descrição está mapeada e o complemento NÃO está - num
    template que tenha a coluna própria, a bitola continua indo nela.
    """
    if tabela_cfg.get("fonte_dados") != "itens":
        return linhas_dados
    nomes = {c[0] for c in colunas}
    if "descricao" not in nomes or "complemento" in nomes:
        return linhas_dados
    saida = []
    for dados in linhas_dados:
        complemento = (dados.get("complemento") or "").strip()
        descricao = (dados.get("descricao") or "").strip()
        if complemento and complemento.lower() not in descricao.lower():
            dados = {**dados, "descricao": f"{descricao} - {complemento}" if descricao else complemento}
        saida.append(dados)
    return saida


# Texto que o template usa só para marcar "o dado vem aqui": XXX, XX / XX,
# 1/X, dd/mm/aa, 0A. Mesmos padrões da tela de mapeamento.
_RESERVADO = re.compile(r"^(?:[xX\s/\-_.#]+|\d+\s*/\s*[xX]|(?:dd|mm|aa)[/\-. ].*|\d*[a-zA-Z])$")


def _repetir_campos_nas_outras_abas(wb, aba_origem, campos, valores):
    """Repete os campos do carimbo nas outras abas do template.

    O carimbo da CBA aparece em TODA aba (a Capa diz "FOLHA: 1/X", a aba da
    lista diz "2/X"), nas mesmas células. O mapeamento, porém, é de uma aba
    só: o número do cliente e o da contratada saíam preenchidos na Capa e
    continuavam "XXX" na folha da lista - documento entregue meio preenchido
    (constatado em 2026-11-15).

    Só escreve onde a célula da outra aba ainda tem **espaço reservado**
    (XXX, 0A, dd/mm/aa). Célula com conteúdo de verdade não é tocada: se
    aquela coordenada ali não for o carimbo, nada acontece.
    """
    for ws in wb.worksheets:
        if ws is aba_origem:
            continue
        for campo, coord in (campos or {}).items():
            if campo not in valores:
                continue
            try:
                cel = ws[coord]
            except Exception:
                continue
            if isinstance(cel, MergedCell):
                continue
            atual = cel.value
            if atual is None or not isinstance(atual, str) or not _RESERVADO.match(atual.strip()):
                continue
            _definir_com_quebra(ws, coord, valores[campo])


def _limpar_formulas_sem_dado(ws, tabela_cfg, colunas):
    """Apaga, nas linhas SEM item, as fórmulas que o template usa para buscar
    material na matriz dele.

    O template da CBA traz uma matriz própria de materiais (aba "Lista
    Codificada", 906 linhas) e cada linha da tabela tem um VLOOKUP contra
    ela. O JNC não usa essa matriz: o material vem do cadastro do próprio
    sistema. Resultado: as linhas que a lista não preenche ficam com a
    fórmula buscando um código vazio, e o Excel mostra **#N/D** - 160 linhas
    assim numa lista de 5 itens (medido na lista 56, em 2026-11-15). Vira
    documento entregue cheio do que parece erro.

    Só apaga onde a coluna-chave da linha está vazia, e só célula que é
    fórmula: linha preenchida e valor digitado pelo cliente não são tocados.
    """
    if tabela_cfg.get("fonte_dados") != "itens":
        return
    chave = next((c for c in colunas if c[0] == "codigo"), None)
    if not chave:
        return  # sem coluna de código não dá para saber se a linha está vazia
    for linha in range(tabela_cfg["linha_inicial"], ws.max_row + 1):
        if ws.cell(row=linha, column=chave[1]).value not in (None, ""):
            continue
        for _, col_ini, col_fim in colunas:
            for col in range(col_ini, col_fim + 1):
                cel = ws.cell(row=linha, column=col)
                if isinstance(cel, MergedCell):
                    continue
                if isinstance(cel.value, str) and cel.value.startswith("="):
                    cel.value = None


def _texto_cabecalho(ws, linha, colunas):
    """Texto das células de cabeçalho da tabela numa linha, normalizado -
    serve para reconhecer o mesmo cabeçalho repetido nas folhas seguintes."""
    textos = []
    for _, col_ini, _ in colunas:
        valor = ws.cell(row=linha, column=col_ini).value
        textos.append(re.sub(r"\s+", " ", str(valor)).strip().lower() if valor not in (None, "") else "")
    return tuple(textos)


def _assinatura_linha(ws, linha, colunas, mesclas_por_linha):
    """Como uma linha da tabela "parece": as mesclagens de uma linha só que
    ela tem dentro das colunas da tabela (no template da CBA: C:D e E:M).
    É o que distingue uma linha de item de uma linha do carimbo."""
    col_min = min(c[1] for c in colunas)
    col_max = max(c[2] for c in colunas)
    return frozenset((c1, c2) for c1, c2 in mesclas_por_linha.get(linha, ()) if c1 >= col_min and c2 <= col_max)


def _blocos_da_tabela(ws, tabela_cfg, colunas):
    """Onde cada folha do template guarda a sua parte da tabela.

    O template da CBA não é uma tabela comprida: a aba da lista tem várias
    FOLHAS, uma embaixo da outra, cada uma com o próprio carimbo e o próprio
    cabeçalho "Item | Código SAP | Descrição...". O motor escrevia os itens
    em sequência a partir da 1ª folha e, passada a última linha dela,
    escrevia POR CIMA do carimbo da folha 2 - duplicando mesclagens em cima
    das do carimbo, o que o Excel acusa como arquivo corrompido ("Mesclar
    células" removido no reparo). Apareceu com a Lista de Compras, que soma
    várias listas e passa de uma folha (16/11/2026).

    Devolve [(linha_inicial, capacidade), ...], uma entrada por folha: a 1ª
    é a do mapeamento; as outras, cada linha abaixo que repete o texto do
    cabeçalho da tabela. A capacidade de cada folha é medida no próprio
    arquivo - linhas seguidas com a mesma cara da linha-molde (mesmas
    mesclagens) -, porque o mapeamento costuma marcar só UMA linha de molde.
    Template sem cabeçalho repetido = uma folha só, comportamento de antes."""
    inicio = tabela_cfg["linha_inicial"]
    capacidade_mapeada = tabela_cfg["linha_final_molde"] - inicio + 1
    cabecalho = _texto_cabecalho(ws, inicio - 1, colunas)
    if capacidade_mapeada < 1 or sum(1 for t in cabecalho if t) < 2:
        return [(inicio, capacidade_mapeada)]
    inicios = [inicio]
    for linha in range(inicio + 1, ws.max_row + 1):
        if _texto_cabecalho(ws, linha, colunas) == cabecalho:
            inicios.append(linha + 1)
    if len(inicios) == 1:
        return [(inicio, capacidade_mapeada)]

    mesclas_por_linha = {}
    for m in ws.merged_cells.ranges:
        if m.min_row == m.max_row:
            mesclas_por_linha.setdefault(m.min_row, []).append((m.min_col, m.max_col))
    molde = _assinatura_linha(ws, tabela_cfg["linha_estilo"], colunas, mesclas_por_linha)
    blocos = []
    for i, ini in enumerate(inicios):
        limite = inicios[i + 1] - 1 if i + 1 < len(inicios) else ws.max_row + 1  # nunca invade a próxima folha
        if molde:
            fim = ini
            while fim < limite and _assinatura_linha(ws, fim, colunas, mesclas_por_linha) == molde:
                fim += 1
            cap = fim - ini
        else:
            cap = min(capacidade_mapeada, limite - ini)
        blocos.append((ini, max(cap, 1)))
    return blocos


def _repetir_carimbo_nas_folhas(ws, deslocamentos, campos, valores):
    """Preenche o carimbo das folhas 2, 3... da mesma aba, nas mesmas
    posições da 1ª folha deslocadas para baixo. Mesma trava de sempre: só
    escreve onde a célula ainda tem espaço reservado (XXX, 0A)."""
    for desloc in deslocamentos:
        for campo, coord in (campos or {}).items():
            if campo not in valores:
                continue
            m = re.match(r"^([A-Z]+)(\d+)$", str(coord))
            if not m:
                continue
            destino = f"{m.group(1)}{int(m.group(2)) + desloc}"
            cel = ws[destino]
            if isinstance(cel, MergedCell):
                continue
            atual = cel.value
            if not isinstance(atual, str) or not _RESERVADO.match(atual.strip()):
                continue
            _definir_com_quebra(ws, destino, valores[campo])


def _preencher_tabela(ws, tabela_cfg, linhas_dados, campos=None, valores=None):
    """tabela_cfg vem do mapeamento salvo: fonte_dados, linha_inicial,
    linha_final_molde, linha_estilo, colunas ([nome, col_ini, col_fim]),
    col_direita_impressao. linhas_dados é a lista de dicts (um por item, por
    exemplo) a escrever a partir da linha_inicial. Quando o template tem a
    tabela repetida em várias folhas, segue para a folha seguinte ao encher
    uma; só depois da última folha duplica o estilo da linha_estilo para
    criar linhas novas, como sempre fez."""
    colunas = [tuple(c) for c in tabela_cfg["colunas"]]
    linha_final_molde = tabela_cfg["linha_final_molde"]
    linha_estilo = tabela_cfg["linha_estilo"]
    linhas_dados = _descricao_com_complemento(tabela_cfg, colunas, linhas_dados)
    blocos = _blocos_da_tabela(ws, tabela_cfg, colunas)

    posicoes = []  # linha de cada item, folha por folha
    for ini, cap in blocos:
        posicoes.extend(range(ini, ini + cap))
    linha = None
    for i, dados in enumerate(linhas_dados):
        if i < len(posicoes):
            linha = posicoes[i]
        else:
            # Passou da última folha pronta do template: cresce para baixo
            # dela, copiando o estilo da linha-molde (o comportamento antigo).
            linha += 1
            _duplicar_linha_estilo(ws, linha_estilo, linha, colunas)
        _escrever_linha_grade(ws, linha, colunas, dados)
    folhas_usadas = 1
    if linha is not None:
        folhas_usadas = 1 + sum(1 for ini, _ in blocos[1:] if linha >= ini)
    if len(blocos) > 1 and folhas_usadas > 1:
        deslocamentos = [ini - blocos[0][0] for ini, _ in blocos[1:folhas_usadas]]
        _repetir_carimbo_nas_folhas(ws, deslocamentos, campos, valores or {})
    _limpar_formulas_sem_dado(ws, tabela_cfg, colunas)
    if len(blocos) > 1 and len(linhas_dados) <= len(posicoes):
        # Template em folhas: imprime até o fim da última folha usada, não
        # as folhas vazias que sobraram do molde do cliente.
        if folhas_usadas < len(blocos):
            periodo_inicio = blocos[folhas_usadas][0] - blocos[0][0]
            ultima_linha = periodo_inicio + _primeira_linha_impressao(tabela_cfg) - 1
        else:
            ultima_linha = ws.max_row
        col_direita = max(tabela_cfg["col_direita_impressao"], ws.max_column)
        _ajustar_area_impressao(ws, tabela_cfg.get("canto_superior_impressao", "A1"), ultima_linha, col_direita)
        return
    linha_escrita = linha if linha is not None else tabela_cfg["linha_inicial"] - 1
    ultima_linha = max(linha_final_molde, linha_escrita)
    # A área de impressão cobre o documento INTEIRO, não só o que foi
    # mapeado - o template do cliente costuma ter colunas/linhas com
    # conteúdo ou formatação (ex.: "Valor Unitário"/"Total" com fórmula
    # própria) que ninguém mapeia porque o sistema não guarda esse dado,
    # mas ainda fazem parte visual da folha dele. Cortar com base só no que
    # foi mapeado já causou relatório saindo com colunas de verdade faltando
    # (reportado com print em 2026-09-22). ws.max_row/max_column refletem
    # tudo que já está na planilha - o template original mais as linhas que
    # acabamos de escrever acima - então nunca deixam nada de fora.
    ultima_linha = max(ultima_linha, ws.max_row)
    col_direita = max(tabela_cfg["col_direita_impressao"], ws.max_column)
    # "canto_superior_impressao" é opcional no mapeamento (default A1) - só
    # existe pra preservar templates migrados cuja área de impressão original
    # não começava no canto absoluto da planilha (ex.: linha/coluna 1 em
    # branco de propósito, fora da área impressa do template do cliente).
    _ajustar_area_impressao(ws, tabela_cfg.get("canto_superior_impressao", "A1"), ultima_linha, col_direita)


def _primeira_linha_impressao(tabela_cfg):
    m = re.match(r"^[A-Z]+(\d+)$", tabela_cfg.get("canto_superior_impressao", "A1"))
    return int(m.group(1)) if m else 1


def _ajustar_area_impressao(ws, canto_superior, ultima_linha, col_direita):
    """O template costuma vir com área e escala de impressão fixas pro tamanho
    original. Se a lista tiver mais linhas que isso, a área de impressão
    precisa crescer junto - senão as linhas extras existem na planilha mas
    não aparecem ao imprimir/exportar (ficam "cortadas"). Troca a escala
    fixa por "encolher até a largura da página" pra nenhuma coluna nunca
    ficar cortada horizontalmente, não importa o conteúdo."""
    ws.print_area = f"{canto_superior}:{get_column_letter(col_direita)}{ultima_linha}"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _campos_lista(lista, versao):
    """Valores dos campos únicos (cabeçalho) pra uma Lista por Desenho -
    mesmos nomes de campo que a tela de mapeamento oferece."""
    return {
        "projeto": lista["projeto_nome"], "subtitulo": lista.get("subtitulo") or "",
        "area": lista.get("area_titulo") or "", "disciplina": lista.get("disciplina") or "",
        "titulo": lista.get("titulo") or "", "numero_cliente": lista.get("numero_cliente") or "",
        "numero_projetista": lista.get("numero_fornecedor") or "", "rev": _rev_exibicao(lista, versao),
        "numero_desenho": lista.get("numero_desenho") or "",
        "referencia_desenho": f"DESENHO DE REFERÊNCIA : {lista.get('numero_desenho') or ''}",
    }


def _linhas_itens(itens):
    linhas = []
    for idx, item in enumerate(itens, start=1):
        linhas.append({
            "item": idx, "codigo": item["codigo"], "descricao": item["descricao"],
            "referencia": item["fabricante"] or "", "complemento": item["bitola"] or "",
            "unidade": item["unidade"], "quant_atual": float(item["quantidade"]),
            "quant_anterior": float(item["quantidade_anterior"]),
        })
    return linhas


def _descricao_revisao(v):
    """Coluna DESCRIÇÃO do histórico de revisões.

    Era a observação digitada na emissão - e ela quase nunca é digitada: no
    banco, 28 das versões emitidas estão com a observação em branco, e a
    coluna saía vazia no documento impresso. O que aquela linha de revisão
    descreve é o **tipo de emissão** escolhido ao emitir (TE, obrigatório
    desde sempre): "PARA APROVAÇÃO", "PARA CONSTRUÇÃO". A letra sozinha já
    vai na coluna TE ao lado; aqui vai o que ela significa.

    Havendo observação, ela entra depois do texto do TE: é informação que
    alguém se deu ao trabalho de escrever, e sumir com ela seria perder
    dado do documento."""
    te = (v["tipo_emissao"] or "").strip().upper()
    texto = TIPOS_EMISSAO.get(te, "")
    observacao = (v["observacoes"] or "").strip()
    if texto and observacao:
        return f"{texto} — {observacao}"
    return texto or observacao or "-"


def _linhas_revisoes(lista, versao, historico):
    linhas = []
    for v in (h for h in historico if h["status"] == "salvo"):
        eh_atual = versao is not None and v["versao"] == versao["versao"]
        data_txt = _data_emissao_exibicao(lista, versao) if eh_atual else v["criado_em"].strftime("%d/%m/%Y")
        linhas.append({
            "rev": v["versao"], "te": v["tipo_emissao"] or "-", "descricao": _descricao_revisao(v),
            "por": _assinatura_curta(lista, "elaborador_nome", "elaborador_sigla"),
            "ver": _assinatura_curta(lista, "verificador_nome", "verificador_sigla"),
            "apr": _assinatura_curta(lista, "aprovador_nome", "aprovador_sigla"),
            "aut": _assinatura_curta(lista, "autorizado_nome", "autorizado_sigla"),
            "data": data_txt,
        })
    return linhas


# ---------- Campos pro template opcional de Planilha de Quantidades ----------
# Mesmos nomes de campo que a tela de mapeamento oferece pro tipo
# "planilha_quantidades" (ver CAMPOS_MAPEAMENTO_POR_TIPO no app.js).
def _campos_planilha_pq(projeto, versao):
    return {
        "projeto": f"{projeto['codigo']} — {projeto['nome']}",
        "cliente": projeto.get("cliente_nome") or "",
        "rev": str(versao["versao"]) if versao else "-",
        "data": versao["criado_em"].strftime("%d/%m/%Y") if versao else "-",
    }


def _linhas_itens_pq(itens):
    linhas = []
    for idx, item in enumerate(itens, start=1):
        linhas.append({
            "item": idx, "codigo": item["codigo"], "descricao": item["descricao"],
            "referencia": item["fabricante"] or "", "complemento": item["bitola"] or "",
            "unidade": item["unidade"], "quantidade_base": float(item["quantidade_base"]),
            "percentual": f"{float(item['percentual']):g}%",
            "quantidade_atualizada": float(item["quantidade_atualizada"]),
        })
    return linhas


# ---------- Campos da Lista de Compras ----------
# A Lista de Compras sai no template do cliente com o MESMO carimbo da Lista
# por Desenho: os campos levam os nomes da Lista por Desenho (é o mapeamento
# do template de Lista de Materiais que vai ser usado na maioria dos casos)
# mais os nomes antigos do template próprio de Compras (projeto, cliente,
# data), para um template de Compras já mapeado continuar funcionando.
def _cabecalho_compras(versao):
    """Carimbo gravado na versão, com Rev. e Data no mesmo tipo que as
    colunas da Lista por Desenho (int e date), para reaproveitar
    _rev_exibicao e _data_emissao_exibicao sem nenhum caso especial."""
    from lista_compras import cabecalho_dict  # import aqui: evita ciclo na carga dos blueprints
    cab = dict(cabecalho_dict(versao.get("cabecalho"))) if versao else {}
    rev = cab.get("rev_manual")
    if rev not in (None, ""):
        try:
            cab["rev_manual"] = int(rev)
        except (TypeError, ValueError):
            pass  # texto livre ("0A") vai como foi digitado
    else:
        cab.pop("rev_manual", None)
    data = cab.get("data_emissao_manual")
    if isinstance(data, str):
        try:
            cab["data_emissao_manual"] = datetime.date.fromisoformat(data[:10])
        except ValueError:
            cab.pop("data_emissao_manual", None)
    return cab


def _campos_lista_compras(projeto, versao):
    cab = _cabecalho_compras(versao)
    numero_documento = cab.get("numero_documento") or ""
    return {
        "projeto": projeto["nome"], "cliente": projeto.get("cliente_nome") or "",
        "subtitulo": cab.get("subtitulo") or "", "area": cab.get("area_titulo") or "",
        "disciplina": cab.get("disciplina") or "", "titulo": cab.get("titulo") or "",
        "numero_cliente": cab.get("numero_cliente") or "",
        "numero_projetista": cab.get("numero_fornecedor") or "",
        "rev": _rev_exibicao(cab, versao), "data": _data_emissao_exibicao(cab, versao),
        "numero_desenho": numero_documento, "referencia_desenho": "",
    }


def _versoes_compras_emitidas(projeto_id):
    return db.query_all(
        """SELECT id, versao, status, observacoes, criado_em, cabecalho FROM lista_compras_versoes
           WHERE projeto_id = %s AND status = 'salvo' ORDER BY versao""",
        (projeto_id,),
    )


def _linhas_revisoes_compras(versao, historico):
    """Histórico de revisões do carimbo: uma linha por versão emitida até a
    exibida, cada uma com os assinantes e a data DAQUELA versão. A Lista de
    Compras não tem tipo de emissão (TE), então a descrição é a observação
    digitada ao emitir, ou o próprio nome do documento."""
    if not versao:
        return []
    linhas = []
    for v in historico:
        if v["versao"] > versao["versao"]:
            break
        cab = _cabecalho_compras(v)
        linhas.append({
            "rev": _rev_exibicao(cab, v), "te": "-",
            "descricao": (v["observacoes"] or "").strip() or "EMITIDO PARA COMPRA",
            "por": _assinatura_curta(cab, "elaborador_nome", "elaborador_sigla"),
            "ver": _assinatura_curta(cab, "verificador_nome", "verificador_sigla"),
            "apr": _assinatura_curta(cab, "aprovador_nome", "aprovador_sigla"),
            "aut": _assinatura_curta(cab, "autorizado_nome", "autorizado_sigla"),
            "data": _data_emissao_exibicao(cab, v),
        })
    return linhas


def _quantidades_compras_anterior(versao, historico):
    """Quantidade de cada material na versão emitida imediatamente anterior
    (coluna 'quant. anterior' do template da Lista de Materiais)."""
    anteriores = [v for v in historico if versao and v["versao"] < versao["versao"]]
    if not anteriores:
        return {}
    rows = db.query_all(
        "SELECT material_id, quantidade FROM lista_compras_itens WHERE versao_id = %s",
        (anteriores[-1]["id"],),
    )
    return {r["material_id"]: float(r["quantidade"]) for r in rows}


def _linhas_itens_compras(itens, anteriores=None):
    anteriores = anteriores or {}
    linhas = []
    for idx, item in enumerate(itens, start=1):
        quantidade = float(item["quantidade"])
        linhas.append({
            "item": idx, "codigo": item["codigo"], "descricao": item["descricao"],
            "referencia": item["fabricante"] or "", "complemento": item["bitola"] or "",
            "unidade": item["unidade"], "quantidade": quantidade,
            "quant_atual": quantidade, "quant_anterior": anteriores.get(item["material_id"], 0.0),
        })
    return linhas


def _template_projeto(projeto_id, tipo):
    """Busca o template mapeado desse projeto/tipo. Devolve None se o
    projeto não tiver nenhum template desse tipo mapeado ainda. O template é
    do PROJETO, não do cliente - um mesmo cliente pode ter templates
    diferentes em projetos diferentes, então não dá pra compartilhar por
    cliente."""
    if not projeto_id:
        return None
    row = db.query_one(
        "SELECT arquivo, mapeamento FROM projetos_templates WHERE projeto_id = %s AND tipo = %s AND mapeamento IS NOT NULL",
        (projeto_id, tipo),
    )
    if not row:
        return None
    mapeamento = row["mapeamento"]
    if isinstance(mapeamento, str):
        mapeamento = json.loads(mapeamento)
    return row["arquivo"], mapeamento


def _campos_de_todas_as_abas(mapeamento):
    """Coordenadas do carimbo mapeadas em qualquer aba: o carimbo das folhas
    é o mesmo em todas as abas do template (ver _repetir_campos_nas_outras_abas)."""
    campos = {}
    for aba_cfg in mapeamento.get("abas", []):
        for campo, coord in (aba_cfg.get("campos") or {}).items():
            campos.setdefault(campo, coord)
    return campos


def _preencher_template_generico(arquivo_bytes, mapeamento, dados_por_fonte):
    """Abre o template do cliente (bytes do banco) e devolve o Workbook com
    os dados preenchidos nas células que o mapeamento indica - sem tocar em
    nenhuma formatação que já vem no próprio arquivo."""
    wb = openpyxl.load_workbook(io.BytesIO(arquivo_bytes))
    campos_valores = dados_por_fonte.get("_campos", {})

    # O bloco de títulos vem ANTES dos campos mapeados, e em TODAS as abas,
    # achado pelo próprio arquivo: é o que faz um template novo já sair
    # preenchido no primeiro download, sem ninguém apontar célula. O que ele
    # ocupa fica reservado, para um campo mapeado não repetir o mesmo texto
    # noutra altura do carimbo.
    reservadas = {ws.title: _preencher_blocos_de_titulo(ws, campos_valores) for ws in wb.worksheets}

    for aba_cfg in mapeamento.get("abas", []):
        if aba_cfg["origem"] >= len(wb.worksheets):
            continue  # template foi substituído por um com menos abas depois do mapeamento
        ws = wb.worksheets[aba_cfg["origem"]]
        _preencher_campos(ws, aba_cfg.get("campos", {}), campos_valores,
                          reservadas=reservadas.get(ws.title, set()))
        _repetir_campos_nas_outras_abas(wb, ws, aba_cfg.get("campos", {}), campos_valores)
        for tabela_cfg in aba_cfg.get("tabelas", []):
            linhas_dados = dados_por_fonte.get(tabela_cfg["fonte_dados"], [])
            _preencher_tabela(ws, tabela_cfg, linhas_dados,
                              campos=_campos_de_todas_as_abas(mapeamento), valores=campos_valores)
            # A aba com a tabela de itens é a "principal" do arquivo - renomeá-la
            # pro número do desenho facilita identificar o arquivo baixado
            # (mesmo comportamento de quando isso era fixo pro template da Ausenco).
            if tabela_cfg["fonte_dados"] == "itens" and campos_valores.get("numero_desenho"):
                ws.title = _titulo_aba_valido(campos_valores["numero_desenho"])
    return wb


@relatorios_bp.get("/api/listas/<int:lista_id>/relatorio/excel")
@login_required
def relatorio_excel(lista_id):
    pid = projeto_da_lista(lista_id)
    if pid is None or not projeto_permitido(pid):
        return jsonify({"erro": "Sem permissão para este relatório"}), 403
    ctx = _carregar_contexto(lista_id, request.args.get("versao_id", type=int))
    if not ctx:
        return jsonify({"erro": "Lista não encontrada"}), 404
    lista, versao, itens, historico = ctx["lista"], ctx["versao"], ctx["itens"], ctx["historico"]

    template = _template_projeto(lista.get("projeto_id"), "lista_materiais")
    if not template:
        return jsonify({
            "erro": "Este projeto ainda não tem um template de Lista de Materiais mapeado. "
                    "Vá na Lista por Desenho do projeto e use o botão \"Template\" pra enviar e mapear o dele."
        }), 400
    arquivo_bytes, mapeamento = template
    dados_por_fonte = {
        "_campos": _campos_lista(lista, versao),
        "itens": _linhas_itens(itens),
        "revisoes": _linhas_revisoes(lista, versao, historico),
    }
    try:
        wb = _preencher_template_generico(arquivo_bytes, mapeamento, dados_por_fonte)
        buf = io.BytesIO()
        wb.save(buf)
    except Exception:
        # Template do cliente com algo que o mapeamento não previu (célula
        # mesclada de um jeito inesperado, aba removida depois de mapeada,
        # etc.) - melhor um erro claro pra rever o mapeamento do que a
        # pessoa cair numa tela de erro genérica do servidor.
        log_erros.registrar(f"Excel da Lista por Desenho (lista {lista_id})")
        return jsonify({
            "erro": "Não foi possível gerar o Excel com o template mapeado desse cliente. "
                    "Reveja o mapeamento em Lista por Desenho → Template, ou avise o suporte."
        }), 500
    buf.seek(0)
    nome_arquivo = f"lista_{lista['numero_desenho']}_rev{versao['versao'] if versao else 0}.xlsx"
    return send_file(buf, as_attachment=True, download_name=nome_arquivo,
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@relatorios_bp.get("/api/projetos/<int:projeto_id>/relatorio/excel")
@login_required
def relatorio_projeto_excel(projeto_id):
    ctx = _carregar_contexto_projeto(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, desenhos, consolidado = ctx["projeto"], ctx["desenhos"], ctx["consolidado"]
    empresa = ctx["config"].get("nome_empresa", "")

    wb = openpyxl.Workbook()
    fino = Side(style="thin", color="000000")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esquerda = Alignment(horizontal="left", vertical="center", wrap_text=True)

    def cabecalho_pagina(ws, largura, subtitulo):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=largura)
        c = ws.cell(row=1, column=1, value=f"{projeto['codigo']} — {projeto['nome']}")
        c.font, c.alignment = Font(bold=True, size=13), centro
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=largura)
        c = ws.cell(row=2, column=1, value=subtitulo)
        c.font, c.alignment = Font(bold=True, size=10), centro
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=largura)
        c = ws.cell(row=3, column=1, value=f"Cliente: {projeto['cliente_nome'] or '-'}    |    Empresa: {empresa}")
        c.font, c.alignment = Font(size=9), centro

    def tabela_com_cabecalho(ws, linha, largura, titulos):
        for col, titulo in enumerate(titulos, start=1):
            cel = ws.cell(row=linha, column=col, value=titulo)
            cel.font = Font(bold=True, size=10, color="FFFFFF")
            cel.fill = openpyxl.styles.PatternFill("solid", fgColor="1f3a5f")
            cel.alignment, cel.border = centro, borda
        return linha + 1

    ws_resumo = wb.active
    ws_resumo.title = "Resumo Consolidado"
    cabecalho_pagina(ws_resumo, 7, "RESUMO CONSOLIDADO DE MATERIAIS (todas as listas, última versão)")
    linha = tabela_com_cabecalho(ws_resumo, 5, 7, ["Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade", "Desenhos"])
    for item in consolidado:
        valores = [item["codigo"], item["descricao"], item["fabricante"] or "", item["bitola"] or "",
                   item["quantidade"], item["unidade"], ", ".join(sorted(item["desenhos"]))]
        for col, valor in enumerate(valores, start=1):
            cel = ws_resumo.cell(row=linha, column=col, value=valor)
            cel.border = borda
            cel.alignment = esquerda if col in (2, 7) else centro
        linha += 1
    if not consolidado:
        ws_resumo.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=7)
        ws_resumo.cell(row=linha, column=1, value="Nenhum material cadastrado em nenhuma lista deste projeto.").alignment = centro
    for i, w in enumerate([14, 34, 20, 12, 12, 10, 20], start=1):
        ws_resumo.column_dimensions[get_column_letter(i)].width = w

    for d in desenhos:
        lista, versao, itens = d["lista"], d["versao"], d["itens"]
        ws = wb.create_sheet(title=lista["numero_desenho"][:31])
        cabecalho_pagina(ws, 6, f"Desenho {lista['numero_desenho']} — {lista['titulo'] or ''}")
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=6)
        ws.cell(row=4, column=1, value=f"Revisão: {versao['versao'] if versao else '-'}    |    Nº Cliente: {lista['numero_cliente'] or '-'}    |    Nº Fornecedor: {lista['numero_fornecedor'] or '-'}").alignment = centro
        linha = tabela_com_cabecalho(ws, 6, 6, ["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade"])
        for idx, item in enumerate(itens, start=1):
            valores = [idx, item["codigo"], item["descricao"], item["fabricante"] or "", item["bitola"] or "",
                       float(item["quantidade"])]
            for col, valor in enumerate(valores, start=1):
                cel = ws.cell(row=linha, column=col, value=valor)
                cel.border = borda
                cel.alignment = esquerda if col == 3 else centro
            linha += 1
        if not itens:
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=6)
            ws.cell(row=linha, column=1, value="Nenhum material nesta versão.").alignment = centro
        for i, w in enumerate([6, 14, 34, 20, 12, 12], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"relatorio_projeto_{projeto['codigo']}.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@relatorios_bp.get("/api/projetos/<int:projeto_id>/relatorio/pdf")
@login_required
def relatorio_projeto_pdf(projeto_id):
    ctx = _carregar_contexto_projeto(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, desenhos, consolidado = ctx["projeto"], ctx["desenhos"], ctx["consolidado"]
    empresa = ctx["config"].get("nome_empresa", "")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)

    titulo_estilo = ParagraphStyle("titulo", fontSize=15, leading=18, alignment=1, spaceAfter=8, fontName="Helvetica-Bold")
    subtitulo_estilo = ParagraphStyle("subtitulo", fontSize=11, leading=14, alignment=1, spaceAfter=4, fontName="Helvetica-Bold")
    ref_estilo = ParagraphStyle("ref", fontSize=9, leading=12, alignment=1, spaceAfter=10)
    secao_estilo = ParagraphStyle("secao", fontSize=12, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=4,
                                   textColor=colors.HexColor("#1f3a5f"))
    sub_estilo = ParagraphStyle("sub", fontSize=9, spaceAfter=6)

    elementos = [
        Paragraph(f"{projeto['codigo']} — {projeto['nome']}", titulo_estilo),
        Paragraph("RELATÓRIO FINAL DO PROJETO — CONSOLIDADO DE MATERIAIS", subtitulo_estilo),
        Paragraph(f"Cliente: {projeto['cliente_nome'] or '-'} &nbsp;&nbsp;|&nbsp;&nbsp; Empresa: {empresa} &nbsp;&nbsp;|&nbsp;&nbsp; {len(desenhos)} lista(s) por desenho", ref_estilo),
    ]

    elementos.append(Paragraph("RESUMO CONSOLIDADO (última versão de cada desenho)", secao_estilo))
    dados_consolidado = [["Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade", "Desenhos"]]
    for item in consolidado:
        dados_consolidado.append([item["codigo"], item["descricao"], item["fabricante"] or "-", item["bitola"] or "-",
                                   f"{item['quantidade']:g}", item["unidade"], ", ".join(sorted(item["desenhos"]))])
    if not consolidado:
        dados_consolidado.append(["-", "Nenhum material cadastrado em nenhuma lista deste projeto.", "-", "-", "-", "-", "-"])
    tabela_consolidado = _tabela_quebravel(
        dados_consolidado,
        col_widths=[2.3 * cm, 7 * cm, 4.5 * cm, 2.5 * cm, 2.5 * cm, 2 * cm, 3.5 * cm],
        alinhar_direita={4, 5},
    )
    elementos.append(tabela_consolidado)
    elementos.append(PageBreak())

    for i, d in enumerate(desenhos):
        lista, versao, itens = d["lista"], d["versao"], d["itens"]
        elementos.append(Paragraph(f"Desenho {lista['numero_desenho']} — {lista['titulo'] or ''}", secao_estilo))
        elementos.append(Paragraph(
            f"Revisão: {versao['versao'] if versao else '-'} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Nº Cliente: {lista['numero_cliente'] or '-'} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Nº Fornecedor: {lista['numero_fornecedor'] or '-'}",
            sub_estilo,
        ))
        dados = [["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"]]
        for idx, item in enumerate(itens, start=1):
            dados.append([idx, item["codigo"], item["descricao"], item["fabricante"] or "-",
                          item["bitola"] or "-", item["quantidade"], item["unidade"]])
        if not itens:
            dados.append(["-", "-", "Nenhum material nesta versão.", "-", "-", "-", "-"])
        tabela = _tabela_quebravel(
            dados,
            col_widths=[1.3 * cm, 2.8 * cm, 8 * cm, 4.5 * cm, 2.8 * cm, 2.8 * cm, 2.3 * cm],
            alinhar_direita={0, 5, 6},
        )
        elementos.append(tabela)
        if i < len(desenhos) - 1:
            elementos.append(PageBreak())

    if not desenhos:
        elementos.append(Paragraph("Nenhuma lista por desenho cadastrada neste projeto.", sub_estilo))

    doc.build(elementos)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"relatorio_projeto_{projeto['codigo']}.pdf", mimetype="application/pdf")


def _carregar_projeto_para_relatorio(projeto_id):
    if not projeto_permitido(projeto_id):
        return None
    projeto = db.query_one(
        f"""SELECT p.*, {SQL_NOME_CLIENTE} AS cliente_nome, c.logo_url AS cliente_logo_url
           FROM projetos p LEFT JOIN clientes c ON c.id = p.cliente_id
           WHERE p.id = %s""",
        (projeto_id,),
    )
    if not projeto:
        return None
    config = {c["chave"]: c["valor"] for c in db.query_all("SELECT chave, valor FROM configuracoes")}
    return {"projeto": projeto, "config": config}


def _marca_dagua_preliminar(doc, ativa):
    """Callback onFirstPage/onLaterPages que carimba 'PRELIMINAR' na diagonal
    quando a versão exibida ainda é um rascunho (não emitida)."""
    def desenhar(canvas, _doc):
        if not ativa:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 70)
        canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.15))
        canvas.translate(doc.pagesize[0] / 2, doc.pagesize[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "PRELIMINAR")
        canvas.restoreState()
    return desenhar


def _carregar_versao_itens(projeto, versao_id_param, tipo):
    """Carrega a versão (a informada ou, por padrão, a última salva) e seus
    itens para relatórios de Lista PQ ou Lista de Compras. tipo é sempre um
    literal fixo no código ('pq' ou 'compras'), nunca vindo do usuário."""
    versao_id = versao_id_param or projeto[f"{tipo}_versao_atual_id"]
    if not versao_id:
        return None, []
    versao = db.query_one(
        f"""SELECT v.*, u.nome AS criado_por_nome FROM lista_{tipo}_versoes v
            LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s""",
        (versao_id,),
    )
    itens = db.query_all(
        f"""SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
            FROM lista_{tipo}_itens i JOIN materiais m ON m.id = i.material_id
            WHERE i.versao_id = %s ORDER BY m.codigo""",
        (versao_id,),
    )
    return versao, itens


# =========================================================
# RELATÓRIO — LISTA PQ
# =========================================================
@relatorios_bp.get("/api/projetos/<int:projeto_id>/lista-pq/relatorio/excel")
@login_required
def relatorio_lista_pq_excel(projeto_id):
    ctx = _carregar_projeto_para_relatorio(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, config = ctx["projeto"], ctx["config"]
    versao, itens = _carregar_versao_itens(projeto, request.args.get("versao_id", type=int), "pq")

    # Template do cliente é opcional aqui (diferente da Lista por Desenho) -
    # sem um mapeado, cai no layout padrão de sempre logo abaixo.
    template = _template_projeto(projeto_id, "planilha_quantidades")
    if template:
        arquivo_bytes, mapeamento = template
        dados_por_fonte = {"_campos": _campos_planilha_pq(projeto, versao), "itens": _linhas_itens_pq(itens)}
        try:
            wb = _preencher_template_generico(arquivo_bytes, mapeamento, dados_por_fonte)
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=f"lista_pq_{projeto['codigo']}.xlsx",
                              mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            log_erros.registrar(f"Excel da Planilha de Quantidades (projeto {projeto_id})")
            return jsonify({
                "erro": "Não foi possível gerar o Excel com o template mapeado. "
                        "Reveja o mapeamento em Planilha de Quantidades → Template, ou avise o suporte."
            }), 500

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Planilha de Quantidades"
    largura_total = 8
    fino = Side(style="thin", color="000000")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esquerda = Alignment(horizontal="left", vertical="center", wrap_text=True)

    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    linha = _cabecalho_excel_com_logos(
        ws, largura_total, config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", "PLANILHA DE QUANTIDADES",
        versao["versao"] if versao else "-", data_versao,
    )

    cabecalho = ["Item", "Código", "Descrição", "Fabricante", "Bitola", "Qtd. Base", "% Aplicado", "Qtd. Atualizada", "Unidade"]
    largura_total = len(cabecalho)
    for col, titulo in enumerate(cabecalho, start=1):
        cel = ws.cell(row=linha, column=col, value=titulo)
        cel.font = Font(bold=True, size=10, color="FFFFFF")
        cel.fill = openpyxl.styles.PatternFill("solid", fgColor="1f3a5f")
        cel.alignment, cel.border = centro, borda
    linha += 1
    for idx, item in enumerate(itens, start=1):
        valores = [idx, item["codigo"], item["descricao"], item["fabricante"] or "", item["bitola"] or "",
                   float(item["quantidade_base"]), f"{float(item['percentual']):g}%",
                   float(item["quantidade_atualizada"]), item["unidade"]]
        for col, valor in enumerate(valores, start=1):
            cel = ws.cell(row=linha, column=col, value=valor)
            cel.border = borda
            cel.alignment = esquerda if col == 3 else centro
        linha += 1
    if not itens:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
        ws.cell(row=linha, column=1, value="Nenhuma versão salva da Planilha de Quantidades ainda.").alignment = centro

    for i, w in enumerate([6, 14, 32, 20, 12, 12, 12, 14, 10], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"lista_pq_{projeto['codigo']}.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@relatorios_bp.get("/api/projetos/<int:projeto_id>/lista-pq/relatorio/pdf")
@login_required
def relatorio_lista_pq_pdf(projeto_id):
    ctx = _carregar_projeto_para_relatorio(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, config = ctx["projeto"], ctx["config"]
    versao, itens = _carregar_versao_itens(projeto, request.args.get("versao_id", type=int), "pq")
    rascunho = bool(versao and versao["status"] == "rascunho")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)
    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    elementos = _cabecalho_pdf_com_logos(
        config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", "PLANILHA DE QUANTIDADES",
        versao["versao"] if versao else "-", data_versao,
    )

    dados = [["Item", "Código", "Descrição", "Fabricante", "Bitola", "Qtd. Base", "%", "Qtd. Atualizada", "Unidade"]]
    for idx, item in enumerate(itens, start=1):
        dados.append([idx, item["codigo"], item["descricao"], item["fabricante"] or "-", item["bitola"] or "-",
                      item["quantidade_base"], f"{float(item['percentual']):g}%", item["quantidade_atualizada"], item["unidade"]])
    if not itens:
        dados.append(["-", "-", "Nenhuma versão salva da Planilha de Quantidades ainda.", "-", "-", "-", "-", "-", "-"])

    tabela = _tabela_quebravel(
        dados, col_widths=[1.2 * cm, 2.5 * cm, 6.5 * cm, 3.5 * cm, 2.2 * cm, 2.2 * cm, 1.8 * cm, 2.8 * cm, 2 * cm],
        alinhar_direita={0, 5, 6, 7, 8},
    )
    elementos.append(tabela)
    marca_dagua = _marca_dagua_preliminar(doc, rascunho)
    doc.build(elementos, onFirstPage=marca_dagua, onLaterPages=marca_dagua)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"lista_pq_{projeto['codigo']}.pdf", mimetype="application/pdf")


# =========================================================
# RELATÓRIO — LISTA DE COMPRAS
# =========================================================
@relatorios_bp.get("/api/projetos/<int:projeto_id>/lista-compras/relatorio/excel")
@login_required
def relatorio_lista_compras_excel(projeto_id):
    ctx = _carregar_projeto_para_relatorio(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, config = ctx["projeto"], ctx["config"]
    versao, itens = _carregar_versao_itens(projeto, request.args.get("versao_id", type=int), "compras")

    # Template: o próprio de Lista de Compras, se o projeto tiver um mapeado;
    # senão, o MESMO template de Lista de Materiais do cliente, com o carimbo
    # desta Lista de Compras. Sem nenhum dos dois, cai no layout padrão abaixo.
    template = (_template_projeto(projeto_id, "lista_compras")
                or _template_projeto(projeto_id, "lista_materiais"))
    cab = _cabecalho_compras(versao)
    nome_base = cab.get("numero_documento") or f"lista_compras_{projeto['codigo']}"
    nome_arquivo = f"{nome_base}_rev{_rev_exibicao(cab, versao)}.xlsx" if versao else f"{nome_base}.xlsx"
    if template:
        arquivo_bytes, mapeamento = template
        historico = _versoes_compras_emitidas(projeto_id)
        dados_por_fonte = {
            "_campos": _campos_lista_compras(projeto, versao),
            "itens": _linhas_itens_compras(itens, _quantidades_compras_anterior(versao, historico)),
            "revisoes": _linhas_revisoes_compras(versao, historico),
        }
        try:
            wb = _preencher_template_generico(arquivo_bytes, mapeamento, dados_por_fonte)
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=nome_arquivo,
                              mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            log_erros.registrar(f"Excel da Lista de Compras (projeto {projeto_id})")
            return jsonify({
                "erro": "Não foi possível gerar o Excel com o template mapeado. "
                        "Reveja o mapeamento em Lista de Compras → Template, ou avise o suporte."
            }), 500

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista de Compras"
    fino = Side(style="thin", color="000000")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esquerda = Alignment(horizontal="left", vertical="center", wrap_text=True)

    linha = _cabecalho_excel_com_logos(
        ws, 6, config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", cab.get("titulo") or "LISTA DE COMPRAS",
        _rev_exibicao(cab, versao), _data_emissao_exibicao(cab, versao),
    )

    cabecalho = ["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"]
    largura_total = len(cabecalho)
    for col, titulo in enumerate(cabecalho, start=1):
        cel = ws.cell(row=linha, column=col, value=titulo)
        cel.font = Font(bold=True, size=10, color="FFFFFF")
        cel.fill = openpyxl.styles.PatternFill("solid", fgColor="1f3a5f")
        cel.alignment, cel.border = centro, borda
    linha += 1
    for idx, item in enumerate(itens, start=1):
        valores = [idx, item["codigo"], item["descricao"], item["fabricante"] or "", item["bitola"] or "",
                   float(item["quantidade"]), item["unidade"]]
        for col, valor in enumerate(valores, start=1):
            cel = ws.cell(row=linha, column=col, value=valor)
            cel.border = borda
            cel.alignment = esquerda if col == 3 else centro
        linha += 1
    if not itens:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
        ws.cell(row=linha, column=1, value="Nenhuma versão salva da Lista de Compras ainda.").alignment = centro

    for i, w in enumerate([6, 14, 34, 20, 12, 12, 10], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=nome_arquivo,
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@relatorios_bp.get("/api/projetos/<int:projeto_id>/lista-compras/relatorio/pdf")
@login_required
def relatorio_lista_compras_pdf(projeto_id):
    ctx = _carregar_projeto_para_relatorio(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, config = ctx["projeto"], ctx["config"]
    versao, itens = _carregar_versao_itens(projeto, request.args.get("versao_id", type=int), "compras")
    rascunho = bool(versao and versao["status"] == "rascunho")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)
    cab = _cabecalho_compras(versao)
    elementos = _cabecalho_pdf_com_logos(
        config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", cab.get("titulo") or "LISTA DE COMPRAS",
        _rev_exibicao(cab, versao), _data_emissao_exibicao(cab, versao),
    )

    dados = [["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"]]
    for idx, item in enumerate(itens, start=1):
        dados.append([idx, item["codigo"], item["descricao"], item["fabricante"] or "-", item["bitola"] or "-",
                      item["quantidade"], item["unidade"]])
    if not itens:
        dados.append(["-", "-", "Nenhuma versão salva da Lista de Compras ainda.", "-", "-", "-", "-"])

    tabela = _tabela_quebravel(
        dados, col_widths=[1.3 * cm, 2.8 * cm, 8 * cm, 4.5 * cm, 2.8 * cm, 2.8 * cm, 2.3 * cm],
        alinhar_direita={0, 5, 6},
    )
    elementos.append(tabela)
    marca_dagua = _marca_dagua_preliminar(doc, rascunho)
    doc.build(elementos, onFirstPage=marca_dagua, onLaterPages=marca_dagua)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"lista_compras_{projeto['codigo']}.pdf", mimetype="application/pdf")
