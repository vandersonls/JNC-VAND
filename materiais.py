import io
import unicodedata

from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required
import openpyxl
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

import db
from auth import perfis_permitidos
from auditoria import registrar

materiais_bp = Blueprint("materiais", __name__)

COLUNAS = ["codigo", "descricao", "fabricante", "bitola", "unidade"]


@materiais_bp.get("/api/materiais")
@login_required
def listar_materiais():
    busca = request.args.get("q", "").strip()
    if busca:
        like = f"%{busca}%"
        rows = db.query_all(
            """SELECT * FROM materiais
               WHERE ativo = 1 AND (codigo LIKE %s OR descricao LIKE %s OR fabricante LIKE %s)
               ORDER BY codigo""",
            (like, like, like),
        )
    else:
        rows = db.query_all("SELECT * FROM materiais WHERE ativo = 1 ORDER BY codigo")
    return jsonify(rows)


@materiais_bp.post("/api/materiais")
@perfis_permitidos("master", "administrador")
def criar_material():
    data = request.get_json(force=True) or {}
    faltando = [c for c in COLUNAS if not data.get(c)]
    if faltando:
        return jsonify({"erro": f"Campos obrigatórios: {', '.join(faltando)}"}), 400
    novo_id = db.execute(
        """INSERT INTO materiais (codigo, descricao, fabricante, bitola, unidade)
           VALUES (%s, %s, %s, %s, %s)""",
        tuple(data[c] for c in COLUNAS),
    )
    registrar("criar", "material", novo_id, f"Criou o material {data['codigo']}", depois=data)
    return jsonify({"id": novo_id}), 201


@materiais_bp.put("/api/materiais/<int:material_id>")
@perfis_permitidos("master", "administrador")
def editar_material(material_id):
    data = request.get_json(force=True) or {}
    faltando = [c for c in COLUNAS if not data.get(c)]
    if faltando:
        return jsonify({"erro": f"Campos obrigatórios: {', '.join(faltando)}"}), 400
    antes = db.query_one("SELECT codigo, descricao, fabricante, bitola, unidade FROM materiais WHERE id = %s", (material_id,))
    db.execute(
        """UPDATE materiais SET codigo=%s, descricao=%s, fabricante=%s, bitola=%s, unidade=%s
           WHERE id=%s""",
        (*[data[c] for c in COLUNAS], material_id),
    )
    registrar("editar", "material", material_id, f"Editou o material {data['codigo']}", antes=antes, depois=data)
    return jsonify({"ok": True})


@materiais_bp.delete("/api/materiais/<int:material_id>")
@perfis_permitidos("master", "administrador")
def excluir_material(material_id):
    antes = db.query_one("SELECT codigo, descricao FROM materiais WHERE id = %s", (material_id,))
    db.execute("UPDATE materiais SET ativo = 0 WHERE id = %s", (material_id,))
    if antes:
        registrar("excluir", "material", material_id, f"Excluiu o material {antes['codigo']}", antes=antes)
    return jsonify({"ok": True})


@materiais_bp.post("/api/materiais/excluir-lote")
@perfis_permitidos("master", "administrador")
def excluir_materiais_lote():
    data = request.get_json(force=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"erro": "Nenhum material selecionado"}), 400

    excluidos = []
    for material_id in ids:
        antes = db.query_one("SELECT codigo, descricao FROM materiais WHERE id = %s", (material_id,))
        if antes:
            db.execute("UPDATE materiais SET ativo = 0 WHERE id = %s", (material_id,))
            excluidos.append(antes["codigo"])

    registrar(
        "excluir", "material", None,
        f"Excluiu {len(excluidos)} material(is) em lote: {', '.join(excluidos)}",
        antes={"codigos": excluidos},
    )
    return jsonify({"excluidos": len(excluidos)})


@materiais_bp.get("/api/materiais/exportar/excel")
@login_required
def exportar_excel():
    rows = db.query_all("SELECT * FROM materiais WHERE ativo = 1 ORDER BY codigo")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Materiais"
    cabecalho = ["Código", "Descrição", "Fabricante", "Bitola", "Unidade"]
    ws.append(cabecalho)
    for row in rows:
        ws.append([row["codigo"], row["descricao"], row["fabricante"], row["bitola"], row["unidade"]])
    for i, _ in enumerate(cabecalho, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 22

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="materiais.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@materiais_bp.get("/api/materiais/exportar/pdf")
@login_required
def exportar_pdf():
    rows = db.query_all("SELECT * FROM materiais WHERE ativo = 1 ORDER BY codigo")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    elementos = [Paragraph("Lista de Materiais", styles["Title"])]

    dados = [["Código", "Descrição", "Fabricante", "Bitola", "Unidade"]]
    for row in rows:
        dados.append([row["codigo"], row["descricao"], row["fabricante"] or "", row["bitola"] or "", row["unidade"]])

    tabela = Table(dados, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
    ]))
    elementos.append(tabela)
    doc.build(elementos)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="materiais.pdf", mimetype="application/pdf")


def _normalizar(texto):
    """Remove acentos e deixa minúsculo, para comparar cabeçalhos com tolerância a variações."""
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


# Cada campo interno aceita várias grafias possíveis encontradas em planilhas reais
SINONIMOS = {
    "codigo": ["codigo"],
    "descricao": ["descricao"],
    "fabricante": ["fabricante", "fabricacao", "fabricado", "marca"],
    "bitola": ["bitola"],
    "unidade": ["unidade", "un", "und", "unid"],
}


@materiais_bp.post("/api/materiais/importar/excel")
@perfis_permitidos("master", "administrador")
def importar_excel():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400

    wb = openpyxl.load_workbook(arquivo, data_only=True)
    ws = wb.active

    linhas = list(ws.iter_rows(values_only=True))
    if not linhas:
        return jsonify({"erro": "Planilha vazia"}), 400

    cabecalho = [_normalizar(c) for c in linhas[0]]

    idx = {}
    faltando = []
    for campo, variantes in SINONIMOS.items():
        posicao = next((cabecalho.index(v) for v in variantes if v in cabecalho), None)
        if posicao is None:
            faltando.append(campo)
        else:
            idx[campo] = posicao

    if faltando:
        return jsonify({"erro": f"Colunas não encontradas na planilha: {', '.join(faltando)}"}), 400

    total_linhas = len(linhas) - 1
    ignoradas, erros = 0, []

    linhas_validas = []
    for linha in linhas[1:]:
        codigo = linha[idx["codigo"]]
        if not codigo:
            ignoradas += 1
            continue
        linhas_validas.append((
            str(codigo).strip(),
            linha[idx["descricao"]] or "",
            linha[idx["fabricante"]] or "",
            linha[idx["bitola"]] or "",
            linha[idx["unidade"]] or "",
        ))

    # Descobre de uma vez quais códigos já existem, em vez de 1 SELECT por linha
    # (essencial para não estourar o timeout do servidor em planilhas grandes).
    codigos_existentes = set()
    todos_codigos = [c[0] for c in linhas_validas]
    for i in range(0, len(todos_codigos), 1000):
        lote = todos_codigos[i:i + 1000]
        if not lote:
            continue
        placeholders = ", ".join(["%s"] * len(lote))
        rows = db.query_all(f"SELECT codigo FROM materiais WHERE codigo IN ({placeholders})", tuple(lote))
        codigos_existentes.update(r["codigo"] for r in rows)

    inseridos, atualizados = 0, 0
    ja_vistos = set()
    for codigo, *_ in linhas_validas:
        if codigo in codigos_existentes or codigo in ja_vistos:
            atualizados += 1
        else:
            inseridos += 1
        ja_vistos.add(codigo)

    # Grava tudo em lotes (executemany), bem mais rápido que uma query por linha
    sql_upsert = """
        INSERT INTO materiais (codigo, descricao, fabricante, bitola, unidade, ativo)
        VALUES (%s, %s, %s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            descricao = VALUES(descricao), fabricante = VALUES(fabricante),
            bitola = VALUES(bitola), unidade = VALUES(unidade), ativo = 1
    """
    for i in range(0, len(linhas_validas), 500):
        lote = linhas_validas[i:i + 500]
        if lote:
            db.execute_many(sql_upsert, lote)

    registrar(
        "importar", "material", None,
        f"Importou planilha '{arquivo.filename}': {total_linhas} linha(s) lida(s), "
        f"{inseridos} novos, {atualizados} atualizados, {ignoradas} ignorada(s)",
    )
    return jsonify({
        "total_linhas": total_linhas,
        "inseridos": inseridos,
        "atualizados": atualizados,
        "ignoradas": ignoradas,
        "erros": erros,
    })
