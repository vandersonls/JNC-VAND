import io

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

import db

relatorios_bp = Blueprint("relatorios", __name__)

# 'rascunho' e 'salvo' são os únicos status internos hoje; mapeados para os
# códigos de status de documento usados no selo (padrão de projetos de engenharia).
STATUS_DOCUMENTO = {
    "rascunho": ("A", "Preliminar"),
    "salvo": ("B", "Aprovado"),
}
LEGENDA_STATUS = [("A", "Preliminar"), ("B", "Aprovado"), ("C", "Aprovado com Comentários"), ("D", "Cancelado")]


def _carregar_contexto(lista_id, versao_id=None):
    lista = db.query_one(
        """SELECT ld.*, p.codigo AS projeto_codigo, p.nome AS projeto_nome, c.razao_social AS cliente_nome
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


@relatorios_bp.get("/api/listas/<int:lista_id>/relatorio/excel")
@login_required
def relatorio_excel(lista_id):
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

    linha = 1

    def escrever_mesclado(texto, negrito=False, tamanho=11, italico=False, alinhamento=centro):
        nonlocal linha
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_total)
        cel = ws.cell(row=linha, column=1, value=texto)
        cel.font = Font(bold=negrito, size=tamanho, italic=italico)
        cel.alignment = alinhamento
        linha += 1

    escrever_mesclado(lista["projeto_nome"], negrito=True, tamanho=14)
    escrever_mesclado("LISTA DE MATERIAIS ELÉTRICOS POR DESENHO", negrito=True, tamanho=11)
    escrever_mesclado(lista["titulo"] or lista["numero_desenho"], tamanho=10, italico=True)
    escrever_mesclado(
        f"Doc. Referência: {_doc_referencia(lista)}    |    Revisão: {versao['versao'] if versao else '-'}",
        tamanho=9,
    )
    escrever_mesclado(
        f"Nº do Cliente: {lista['numero_cliente'] or '-'}    |    Nº do Fornecedor: {lista['numero_fornecedor'] or '-'}",
        tamanho=9,
    )
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
    escrever_mesclado("HISTÓRICO DE REVISÕES", negrito=True, tamanho=10, alinhamento=centro)
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
    escrever_mesclado(f"STATUS DO DOCUMENTO:   {legenda_txt}", tamanho=9, alinhamento=esquerda)

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
    ctx = _carregar_contexto(lista_id, request.args.get("versao_id", type=int))
    if not ctx:
        return jsonify({"erro": "Lista não encontrada"}), 404
    lista, versao, itens, historico = ctx["lista"], ctx["versao"], ctx["itens"], ctx["historico"]
    empresa = ctx["config"].get("nome_empresa", "")
    rascunho = bool(versao and versao["status"] == "rascunho")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                             leftMargin=1.2 * cm, rightMargin=1.2 * cm)

    titulo_estilo = ParagraphStyle("titulo", fontSize=15, leading=18, alignment=1, spaceAfter=8, fontName="Helvetica-Bold")
    subtitulo_estilo = ParagraphStyle("subtitulo", fontSize=11, leading=14, alignment=1, spaceAfter=4, fontName="Helvetica-Bold")
    ref_estilo = ParagraphStyle("ref", fontSize=9, leading=12, alignment=1, spaceAfter=10)
    secao_estilo = ParagraphStyle("secao", fontSize=10, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)

    elementos = [
        Paragraph(lista["projeto_nome"], titulo_estilo),
        Paragraph("LISTA DE MATERIAIS ELÉTRICOS POR DESENHO", subtitulo_estilo),
        Paragraph(lista["titulo"] or lista["numero_desenho"], ref_estilo),
        Paragraph(f"Doc. Referência: {_doc_referencia(lista)} &nbsp;&nbsp;|&nbsp;&nbsp; Revisão: {versao['versao'] if versao else '-'}", ref_estilo),
        Paragraph(
            f"Nº do Cliente: {lista['numero_cliente'] or '-'} &nbsp;&nbsp;|&nbsp;&nbsp; Nº do Fornecedor: {lista['numero_fornecedor'] or '-'}",
            ref_estilo,
        ),
    ]

    dados_materiais = [["Item", "Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"]]
    for idx, item in enumerate(itens, start=1):
        dados_materiais.append([idx, item["codigo"], item["descricao"], item["fabricante"] or "",
                                 item["bitola"] or "", str(item["quantidade"]), item["unidade"]])
    if not itens:
        dados_materiais.append(["-", "-", "Nenhum material nesta versão.", "", "", "", ""])

    tabela_materiais = Table(dados_materiais, repeatRows=1,
                              colWidths=[1.5 * cm, 3 * cm, None, 4 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])
    tabela_materiais.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (4, 0), (-1, -1), "CENTER"),
    ]))
    elementos.append(tabela_materiais)

    elementos.append(Paragraph("HISTÓRICO DE REVISÕES", secao_estilo))
    dados_rev = [["Rev.", "Data", "Responsável", "Descrição"]]
    for v in historico:
        dados_rev.append([v["versao"], v["criado_em"].strftime("%d/%m/%Y"), v["criado_por_nome"] or "-", v["observacoes"] or "-"])
    tabela_rev = Table(dados_rev, colWidths=[1.5 * cm, 2.5 * cm, 4 * cm, None])
    tabela_rev.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e5ea")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (2, -1), "CENTER"),
    ]))
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
