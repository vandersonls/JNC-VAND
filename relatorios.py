import io
import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse

import openpyxl
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
from areas import projeto_permitido, projeto_da_lista

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

# 'rascunho' e 'salvo' são os únicos status internos hoje; mapeados para os
# códigos de status de documento usados no selo (padrão de projetos de engenharia).
STATUS_DOCUMENTO = {
    "rascunho": ("A", "Preliminar"),
    "salvo": ("B", "Aprovado"),
}
LEGENDA_STATUS = [("A", "Preliminar"), ("B", "Aprovado"), ("C", "Aprovado com Comentários"), ("D", "Cancelado")]

CEL_ESTILO = ParagraphStyle("cel", fontSize=8, leading=10)
CEL_ESTILO_CABECALHO = ParagraphStyle("cel_cab", fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")


def _tabela_quebravel(dados, col_widths, alinhar_direita=None):
    """Monta uma Table do reportlab em que toda célula é um Paragraph,
    para que o texto quebre linha dentro da largura da coluna em vez de
    transbordar/sobrepor o texto vizinho."""
    alinhar_direita = alinhar_direita or set()
    linhas = []
    for i, linha in enumerate(dados):
        estilo = CEL_ESTILO_CABECALHO if i == 0 else CEL_ESTILO
        linhas.append([Paragraph(str(v), estilo) for v in linha])
    tabela = Table(linhas, colWidths=col_widths, repeatRows=1)
    estilo_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
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
        """SELECT ld.*, p.codigo AS projeto_codigo, p.nome AS projeto_nome,
                  c.razao_social AS cliente_nome, c.logo_url AS cliente_logo_url
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
        """SELECT i.quantidade, i.observacao, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_desenho_itens i JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s ORDER BY m.codigo""",
        (alvo_versao_id,),
    )
    historico = db.query_all(
        """SELECT v.versao, v.status, v.observacoes, v.criado_em, u.nome AS criado_por_nome
           FROM lista_desenho_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por
           WHERE v.lista_desenho_id = %s ORDER BY v.versao""",
        (lista_id,),
    )
    config = {c["chave"]: c["valor"] for c in db.query_all("SELECT chave, valor FROM configuracoes")}

    return {"lista": lista, "versao": versao, "itens": itens, "historico": historico, "config": config}


def _doc_referencia(lista):
    return f"{lista['projeto_codigo']}-{lista['numero_desenho']}"


def _linha_assinaturas(lista):
    """Monta a linha 'Elaborado por / Verificado por / Aprovado por' do carimbo,
    omitindo qualquer papel que não tenha nome preenchido."""
    partes = []
    for rotulo, campo_nome, campo_sigla in (
        ("Elaborado por", "elaborador_nome", "elaborador_sigla"),
        ("Verificado por", "verificador_nome", "verificador_sigla"),
        ("Aprovado por", "aprovador_nome", "aprovador_sigla"),
    ):
        nome = lista.get(campo_nome)
        if not nome:
            continue
        sigla = lista.get(campo_sigla)
        partes.append(f"{rotulo}: {nome}{f' ({sigla})' if sigla else ''}")
    return "    |    ".join(partes)


def _carregar_contexto_projeto(projeto_id):
    """Reúne, para cada Lista por Desenho do projeto, sempre a sua última versão salva."""
    if not projeto_permitido(projeto_id):
        return None
    projeto = db.query_one(
        """SELECT p.*, c.razao_social AS cliente_nome
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
    empresa = ctx["config"].get("nome_empresa", "")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista de Materiais"
    largura_total = 7

    fino = Side(style="thin", color="000000")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esquerda = Alignment(horizontal="left", vertical="center", wrap_text=True)

    def escrever_mesclado(texto, negrito=False, tamanho=11, italico=False, alinhamento=centro, linha_atual=1):
        ws.merge_cells(start_row=linha_atual, start_column=1, end_row=linha_atual, end_column=largura_total)
        cel = ws.cell(row=linha_atual, column=1, value=texto)
        cel.font = Font(bold=negrito, size=tamanho, italic=italico)
        cel.alignment = alinhamento
        return linha_atual + 1

    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    linha = _cabecalho_excel_com_logos(
        ws, largura_total, empresa, ctx["config"].get("logo_url", ""),
        lista["cliente_nome"], lista.get("cliente_logo_url"),
        lista["projeto_nome"], f"LISTA DE MATERIAIS ELÉTRICOS POR DESENHO — {lista['titulo'] or lista['numero_desenho']}",
        versao["versao"] if versao else "-", data_versao,
    )
    linha = escrever_mesclado(
        f"Doc. Referência: {_doc_referencia(lista)}    |    Nº do Cliente: {lista['numero_cliente'] or '-'}    |    Nº do Fornecedor: {lista['numero_fornecedor'] or '-'}",
        tamanho=9, linha_atual=linha,
    )
    assinaturas = _linha_assinaturas(lista)
    if assinaturas:
        linha = escrever_mesclado(assinaturas, tamanho=9, linha_atual=linha)
    linha += 1

    cabecalho = ["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"]
    for col, titulo in enumerate(cabecalho, start=1):
        cel = ws.cell(row=linha, column=col, value=titulo)
        cel.font = Font(bold=True, size=10, color="FFFFFF")
        cel.fill = openpyxl.styles.PatternFill("solid", fgColor="1f3a5f")
        cel.alignment = centro
        cel.border = borda
    linha += 1

    for idx, item in enumerate(itens, start=1):
        valores = [idx, item["codigo"], item["descricao"], item["fabricante"] or "", item["bitola"] or "",
                   float(item["quantidade"]), item["unidade"]]
        for col, valor in enumerate(valores, start=1):
            cel = ws.cell(row=linha, column=col, value=valor)
            cel.border = borda
            cel.alignment = centro if col != 3 else esquerda
        linha += 1
    if not itens:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
        ws.cell(row=linha, column=1, value="Nenhum material nesta versão.").alignment = centro
        linha += 1

    linha += 1
    linha = escrever_mesclado("HISTÓRICO DE REVISÕES", negrito=True, tamanho=10, alinhamento=centro, linha_atual=linha)
    for col, titulo in enumerate(["Rev.", "Data", "Responsável", "Descrição"], start=1):
        cel = ws.cell(row=linha, column=col, value=titulo)
        cel.font = Font(bold=True, size=9)
        cel.border = borda
        cel.alignment = centro
    ws.merge_cells(start_row=linha, start_column=4, end_row=linha, end_column=largura_total)
    linha += 1
    for v in historico:
        ws.cell(row=linha, column=1, value=v["versao"]).border = borda
        ws.cell(row=linha, column=2, value=v["criado_em"].strftime("%d/%m/%Y")).border = borda
        ws.cell(row=linha, column=3, value=v["criado_por_nome"] or "-").border = borda
        cel_desc = ws.cell(row=linha, column=4, value=v["observacoes"] or "-")
        cel_desc.border = borda
        cel_desc.alignment = esquerda
        ws.merge_cells(start_row=linha, start_column=4, end_row=linha, end_column=largura_total)
        for c in range(1, 4):
            ws.cell(row=linha, column=c).alignment = centro
        linha += 1

    linha += 1
    codigo_atual, nome_atual = STATUS_DOCUMENTO.get(versao["status"], ("-", "-")) if versao else ("-", "-")
    legenda_txt = "   ".join(
        f"[{'X' if cod == codigo_atual else ' '}] {cod} - {nome}" for cod, nome in LEGENDA_STATUS
    )
    linha = escrever_mesclado(f"STATUS DO DOCUMENTO:   {legenda_txt}", tamanho=9, alinhamento=esquerda, linha_atual=linha)

    linha += 1
    ws.cell(row=linha, column=1, value=f"Cliente: {lista['cliente_nome'] or '-'}").font = Font(size=9)
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=3)
    ws.cell(row=linha, column=4, value=f"Empresa: {empresa}").font = Font(size=9)
    ws.merge_cells(start_row=linha, start_column=4, end_row=linha, end_column=5)
    ws.cell(row=linha, column=6, value=f"Doc.: {_doc_referencia(lista)}").font = Font(size=9)
    ws.merge_cells(start_row=linha, start_column=6, end_row=linha, end_column=largura_total)

    larguras = [6, 14, 34, 20, 12, 12, 10]
    for i, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    nome_arquivo = f"lista_{lista['numero_desenho']}_rev{versao['versao'] if versao else 0}.xlsx"
    return send_file(buf, as_attachment=True, download_name=nome_arquivo,
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@relatorios_bp.get("/api/listas/<int:lista_id>/relatorio/pdf")
@login_required
def relatorio_pdf(lista_id):
    pid = projeto_da_lista(lista_id)
    if pid is None or not projeto_permitido(pid):
        return jsonify({"erro": "Sem permissão para este relatório"}), 403
    ctx = _carregar_contexto(lista_id, request.args.get("versao_id", type=int))
    if not ctx:
        return jsonify({"erro": "Lista não encontrada"}), 404
    lista, versao, itens, historico = ctx["lista"], ctx["versao"], ctx["itens"], ctx["historico"]
    empresa = ctx["config"].get("nome_empresa", "")
    rascunho = bool(versao and versao["status"] == "rascunho")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)

    ref_estilo = ParagraphStyle("ref", fontSize=9, leading=12, alignment=1, spaceAfter=10)
    secao_estilo = ParagraphStyle("secao", fontSize=10, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)

    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    elementos = _cabecalho_pdf_com_logos(
        empresa, ctx["config"].get("logo_url", ""), lista["cliente_nome"], lista.get("cliente_logo_url"),
        lista["projeto_nome"], f"LISTA DE MATERIAIS ELÉTRICOS POR DESENHO — {lista['titulo'] or lista['numero_desenho']}",
        versao["versao"] if versao else "-", data_versao,
    )
    elementos.append(Paragraph(
        f"Doc. Referência: {_doc_referencia(lista)} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Nº do Cliente: {lista['numero_cliente'] or '-'} &nbsp;&nbsp;|&nbsp;&nbsp; Nº do Fornecedor: {lista['numero_fornecedor'] or '-'}",
        ref_estilo,
    ))
    assinaturas = _linha_assinaturas(lista)
    if assinaturas:
        elementos.append(Paragraph(assinaturas.replace("    |    ", " &nbsp;&nbsp;|&nbsp;&nbsp; "), ref_estilo))

    dados_materiais = [["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"]]
    for idx, item in enumerate(itens, start=1):
        dados_materiais.append([idx, item["codigo"], item["descricao"], item["fabricante"] or "-",
                                 item["bitola"] or "-", item["quantidade"], item["unidade"]])
    if not itens:
        dados_materiais.append(["-", "-", "Nenhum material nesta versão.", "-", "-", "-", "-"])

    tabela_materiais = _tabela_quebravel(
        dados_materiais,
        col_widths=[1.3 * cm, 2.8 * cm, 8 * cm, 4.5 * cm, 2.8 * cm, 2.8 * cm, 2.3 * cm],
        alinhar_direita={0, 5, 6},
    )
    elementos.append(tabela_materiais)

    elementos.append(Paragraph("HISTÓRICO DE REVISÕES", secao_estilo))
    dados_rev = [["Rev.", "Data", "Responsável", "Descrição"]]
    for v in historico:
        dados_rev.append([v["versao"], v["criado_em"].strftime("%d/%m/%Y"), v["criado_por_nome"] or "-", v["observacoes"] or "-"])
    tabela_rev = _tabela_quebravel(
        dados_rev, col_widths=[1.5 * cm, 2.5 * cm, 4 * cm, 16.5 * cm], alinhar_direita={0, 1},
    )
    elementos.append(tabela_rev)

    codigo_atual = STATUS_DOCUMENTO.get(versao["status"], ("-", "-"))[0] if versao else "-"
    dados_status = [[("[X] " if cod == codigo_atual else "[ ] ") + f"{cod} - {nome}" for cod, nome in LEGENDA_STATUS]]
    tabela_status = Table(dados_status, colWidths=[6 * cm] * 4)
    tabela_status.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elementos.append(Spacer(1, 8))
    elementos.append(tabela_status)

    dados_rodape = [[f"Cliente: {lista['cliente_nome'] or '-'}", f"Empresa: {empresa}", f"Documento: {_doc_referencia(lista)}"]]
    tabela_rodape = Table(dados_rodape, colWidths=[9 * cm, 9 * cm, 9 * cm])
    tabela_rodape.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elementos.append(Spacer(1, 4))
    elementos.append(tabela_rodape)

    def marca_dagua(canvas, _doc):
        if not rascunho:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 70)
        canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.15))
        canvas.translate(doc.pagesize[0] / 2, doc.pagesize[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "PRELIMINAR")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=marca_dagua, onLaterPages=marca_dagua)
    buf.seek(0)
    nome_arquivo = f"lista_{lista['numero_desenho']}_rev{versao['versao'] if versao else 0}.pdf"
    return send_file(buf, as_attachment=True, download_name=nome_arquivo, mimetype="application/pdf")


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
        """SELECT p.*, c.razao_social AS cliente_nome, c.logo_url AS cliente_logo_url
           FROM projetos p LEFT JOIN clientes c ON c.id = p.cliente_id
           WHERE p.id = %s""",
        (projeto_id,),
    )
    if not projeto:
        return None
    config = {c["chave"]: c["valor"] for c in db.query_all("SELECT chave, valor FROM configuracoes")}
    return {"projeto": projeto, "config": config}


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
    versao_id = request.args.get("versao_id", type=int) or projeto["pq_versao_atual_id"]
    versao = db.query_one("SELECT v.*, u.nome AS criado_por_nome FROM lista_pq_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s", (versao_id,)) if versao_id else None
    itens = db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_pq_itens i JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s ORDER BY m.codigo""", (versao_id,),
    ) if versao_id else []

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista PQ"
    largura_total = 8
    fino = Side(style="thin", color="000000")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esquerda = Alignment(horizontal="left", vertical="center", wrap_text=True)

    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    linha = _cabecalho_excel_com_logos(
        ws, largura_total, config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", "LISTA PQ",
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
        ws.cell(row=linha, column=1, value="Nenhuma versão salva da Lista PQ ainda.").alignment = centro

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
    versao_id = request.args.get("versao_id", type=int) or projeto["pq_versao_atual_id"]
    versao = db.query_one("SELECT v.*, u.nome AS criado_por_nome FROM lista_pq_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s", (versao_id,)) if versao_id else None
    itens = db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_pq_itens i JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s ORDER BY m.codigo""", (versao_id,),
    ) if versao_id else []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)
    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    elementos = _cabecalho_pdf_com_logos(
        config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", "LISTA PQ",
        versao["versao"] if versao else "-", data_versao,
    )

    dados = [["Item", "Código", "Descrição", "Fabricante", "Bitola", "Qtd. Base", "%", "Qtd. Atualizada", "Unidade"]]
    for idx, item in enumerate(itens, start=1):
        dados.append([idx, item["codigo"], item["descricao"], item["fabricante"] or "-", item["bitola"] or "-",
                      item["quantidade_base"], f"{float(item['percentual']):g}%", item["quantidade_atualizada"], item["unidade"]])
    if not itens:
        dados.append(["-", "-", "Nenhuma versão salva da Lista PQ ainda.", "-", "-", "-", "-", "-", "-"])

    tabela = _tabela_quebravel(
        dados, col_widths=[1.2 * cm, 2.5 * cm, 6.5 * cm, 3.5 * cm, 2.2 * cm, 2.2 * cm, 1.8 * cm, 2.8 * cm, 2 * cm],
        alinhar_direita={0, 5, 6, 7, 8},
    )
    elementos.append(tabela)
    doc.build(elementos)
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
    versao_id = request.args.get("versao_id", type=int) or projeto["compras_versao_atual_id"]
    versao = db.query_one("SELECT v.*, u.nome AS criado_por_nome FROM lista_compras_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s", (versao_id,)) if versao_id else None
    itens = db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_compras_itens i JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s ORDER BY m.codigo""", (versao_id,),
    ) if versao_id else []

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista de Compras"
    fino = Side(style="thin", color="000000")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esquerda = Alignment(horizontal="left", vertical="center", wrap_text=True)

    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    linha = _cabecalho_excel_com_logos(
        ws, 6, config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", "LISTA DE COMPRAS",
        versao["versao"] if versao else "-", data_versao,
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
    return send_file(buf, as_attachment=True, download_name=f"lista_compras_{projeto['codigo']}.xlsx",
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@relatorios_bp.get("/api/projetos/<int:projeto_id>/lista-compras/relatorio/pdf")
@login_required
def relatorio_lista_compras_pdf(projeto_id):
    ctx = _carregar_projeto_para_relatorio(projeto_id)
    if not ctx:
        return jsonify({"erro": "Projeto não encontrado"}), 404
    projeto, config = ctx["projeto"], ctx["config"]
    versao_id = request.args.get("versao_id", type=int) or projeto["compras_versao_atual_id"]
    versao = db.query_one("SELECT v.*, u.nome AS criado_por_nome FROM lista_compras_versoes v LEFT JOIN usuarios u ON u.id = v.criado_por WHERE v.id = %s", (versao_id,)) if versao_id else None
    itens = db.query_all(
        """SELECT i.*, m.codigo, m.descricao, m.fabricante, m.bitola, m.unidade
           FROM lista_compras_itens i JOIN materiais m ON m.id = i.material_id
           WHERE i.versao_id = %s ORDER BY m.codigo""", (versao_id,),
    ) if versao_id else []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)
    data_versao = versao["criado_em"].strftime("%d/%m/%Y") if versao else "-"
    elementos = _cabecalho_pdf_com_logos(
        config.get("nome_empresa", ""), config.get("logo_url", ""),
        projeto["cliente_nome"], projeto.get("cliente_logo_url"),
        f"{projeto['codigo']} — {projeto['nome']}", "LISTA DE COMPRAS",
        versao["versao"] if versao else "-", data_versao,
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
    doc.build(elementos)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"lista_compras_{projeto['codigo']}.pdf", mimetype="application/pdf")
