import io
from datetime import datetime

import openpyxl
from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required

import db
from auth import perfis_permitidos
from auditoria import registrar

config_bp = Blueprint("config", __name__)

# Só estas chaves de configuração podem ser gravadas pela tela do sistema.
# Qualquer outra é ignorada (evita inserção arbitrária de linhas na tabela).
CHAVES_CONFIG_PERMITIDAS = {"nome_empresa", "logo_url", "formato_data"}


@config_bp.get("/api/configuracoes")
@login_required
def listar_configuracoes():
    rows = db.query_all("SELECT chave, valor, descricao FROM configuracoes ORDER BY chave")
    return jsonify(rows)


@config_bp.put("/api/configuracoes")
@perfis_permitidos("master", "administrador")
def atualizar_configuracoes():
    data = request.get_json(force=True) or {}
    aplicadas = {}
    for chave, valor in data.items():
        if chave not in CHAVES_CONFIG_PERMITIDAS:
            continue  # ignora chaves não reconhecidas
        db.execute(
            "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE valor = VALUES(valor)",
            (chave, valor),
        )
        aplicadas[chave] = valor
    registrar("editar", "configuracao", None, "Atualizou as configurações do sistema", depois=aplicadas)
    return jsonify({"ok": True})


def _adicionar_planilha(wb, titulo, colunas, linhas):
    ws = wb.create_sheet(titulo[:31])
    ws.append(colunas)
    for linha in linhas:
        ws.append([linha.get(c, "") for c in colunas])


# Fonte única do que entra no backup completo - reaproveitada pelo painel de
# "Bancos de Dados" (bancos.py) pra gerar o mesmo backup contra QUALQUER
# banco cadastrado ali, não só o principal que este arquivo usa.
PLANILHAS_BACKUP = [
    ("Materiais", ["id", "codigo", "descricao", "fabricante", "bitola", "unidade", "area_id"],
     "SELECT id, codigo, descricao, fabricante, bitola, unidade, area_id FROM materiais WHERE ativo = 1 ORDER BY codigo"),
    ("Clientes", ["id", "razao_social", "nome_fantasia", "cnpj_cpf", "contato", "telefone", "email", "endereco"],
     "SELECT id, razao_social, nome_fantasia, cnpj_cpf, contato, telefone, email, endereco FROM clientes WHERE ativo = 1 ORDER BY razao_social"),
    ("Projetos", ["id", "codigo", "nome", "cliente_id", "status", "numero_cliente", "numero_fornecedor", "area_id"],
     "SELECT id, codigo, nome, cliente_id, status, numero_cliente, numero_fornecedor, area_id FROM projetos ORDER BY codigo"),
    ("Areas", ["id", "nome"], "SELECT id, nome FROM areas ORDER BY nome"),
    ("Usuarios", ["id", "nome", "email", "perfil", "ativo"],
     "SELECT id, nome, email, perfil, ativo FROM usuarios ORDER BY nome"),
    ("Listas por Desenho", ["id", "projeto_id", "numero_desenho", "titulo", "versao_atual_id"],
     "SELECT id, projeto_id, numero_desenho, titulo, versao_atual_id FROM listas_desenho ORDER BY projeto_id, numero_desenho"),
]


@config_bp.get("/api/backup/excel")
@perfis_permitidos("master")
def backup_excel():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for titulo, colunas, sql in PLANILHAS_BACKUP:
        _adicionar_planilha(wb, titulo, colunas, db.query_all(sql))

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    registrar("exportar", "backup", None, "Baixou um backup completo dos dados do sistema")
    nome_arquivo = f"backup_njc_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buffer, as_attachment=True, download_name=nome_arquivo,
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@config_bp.delete("/api/risco/materiais")
@perfis_permitidos("master")
def zerar_materiais():
    total = db.query_one("SELECT COUNT(*) AS n FROM materiais WHERE ativo = 1")["n"]
    db.execute("UPDATE materiais SET ativo = 0 WHERE ativo = 1")
    registrar("excluir", "risco", None, f"Zona de risco: excluiu todos os {total} materiais cadastrados")
    return jsonify({"excluidos": total})


@config_bp.delete("/api/risco/projetos")
@perfis_permitidos("master")
def zerar_projetos():
    total = db.query_one("SELECT COUNT(*) AS n FROM projetos")["n"]
    db.execute("DELETE FROM projetos")
    registrar("excluir", "risco", None, f"Zona de risco: excluiu todos os {total} projetos (e listas/PQ/compras associados)")
    return jsonify({"excluidos": total})


@config_bp.delete("/api/risco/auditoria")
@perfis_permitidos("master")
def zerar_auditoria():
    total = db.query_one("SELECT COUNT(*) AS n FROM auditoria")["n"]
    db.execute("TRUNCATE TABLE auditoria")
    registrar("excluir", "risco", None, f"Zona de risco: zerou o log de auditoria ({total} registros removidos)")
    return jsonify({"excluidos": total})
