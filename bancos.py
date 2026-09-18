"""Painel de "Bancos de Dados" (Configurações -> Bancos de Dados, só master):
registra outras instâncias de MySQL (ex.: produção no Railway, mesmo
enquanto o app roda local pra teste) pra poder, com um clique, testar se
cada uma está no ar e baixar um backup completo (Excel) dela.

Nasceu do episódio de 2026-09-18: o MySQL de produção do Railway ficou
inacessível (assinatura vencida) e não existia nenhum backup completo salvo
fora dele - só extrações parciais e antigas. Esta tela deixa o backup manual
de qualquer banco monitorado a um clique de distância, sem precisar guardar
a connection string em outro lugar (bloco de notas, chat, etc.).

O banco "principal" (o que o próprio app já está usando, via DB_CONFIG em
app.py) sempre aparece como a primeira entrada da lista, mas não é uma linha
de bancos_monitorados - não pode ser editado/removido por aqui, porque é
consequência de onde o processo foi ligado (variáveis de ambiente), não uma
configuração salva no banco.

A senha de cada banco cadastrado fica em texto simples na coluna - mesmo
nível de proteção que MYSQL_URL/DB_PASSWORD já têm hoje como variável de
ambiente. Só master enxerga e mexe nessa tela; a senha nunca volta pro
front depois de salva (só um marcador indicando que existe)."""
import io
from datetime import datetime

import mysql.connector
import openpyxl
from flask import Blueprint, request, jsonify, send_file

import db
from auth import perfis_permitidos
from auditoria import registrar
from configuracoes import PLANILHAS_BACKUP

bancos_bp = Blueprint("bancos", __name__)


def _principal_info():
    from app import DB_CONFIG  # import local evita ciclo (app.py importa este blueprint)
    return {
        "id": "principal", "nome": "Este servidor (banco principal)",
        "host": DB_CONFIG["DB_HOST"], "porta": int(DB_CONFIG["DB_PORT"]),
        "banco": DB_CONFIG["DB_NAME"], "editavel": False,
    }


def _conectar(banco):
    return mysql.connector.connect(
        host=banco["host"], port=banco["porta"], user=banco["usuario"],
        password=banco["senha"], database=banco["banco"], connection_timeout=8,
    )


@bancos_bp.get("/api/bancos")
@perfis_permitidos("master")
def listar_bancos():
    linhas = db.query_all(
        "SELECT id, nome, host, porta, usuario, banco, atualizado_em FROM bancos_monitorados ORDER BY nome"
    )
    for l in linhas:
        l["editavel"] = True
    return jsonify([_principal_info()] + linhas)


@bancos_bp.post("/api/bancos")
@perfis_permitidos("master")
def criar_banco():
    d = request.get_json(force=True) or {}
    obrigatorios = ("nome", "host", "usuario", "senha", "banco")
    if not all((d.get(c) or "").strip() for c in obrigatorios):
        return jsonify({"erro": "Preencha nome, host, usuário, senha e banco"}), 400
    try:
        porta = int(d.get("porta") or 3306)
    except (TypeError, ValueError):
        return jsonify({"erro": "Porta inválida"}), 400
    banco_id = db.execute(
        "INSERT INTO bancos_monitorados (nome, host, porta, usuario, senha, banco) VALUES (%s,%s,%s,%s,%s,%s)",
        (d["nome"].strip(), d["host"].strip(), porta, d["usuario"].strip(), d["senha"], d["banco"].strip()),
    )
    registrar("criar", "banco_monitorado", banco_id, f"Cadastrou o banco monitorado \"{d['nome']}\" ({d['host']})")
    return jsonify({"id": banco_id}), 201


@bancos_bp.put("/api/bancos/<int:banco_id>")
@perfis_permitidos("master")
def editar_banco(banco_id):
    row = db.query_one("SELECT id FROM bancos_monitorados WHERE id = %s", (banco_id,))
    if not row:
        return jsonify({"erro": "Banco não encontrado"}), 404
    d = request.get_json(force=True) or {}
    obrigatorios = ("nome", "host", "usuario", "banco")
    if not all((d.get(c) or "").strip() for c in obrigatorios):
        return jsonify({"erro": "Preencha nome, host, usuário e banco"}), 400
    try:
        porta = int(d.get("porta") or 3306)
    except (TypeError, ValueError):
        return jsonify({"erro": "Porta inválida"}), 400

    # Senha só é trocada se foi digitada de novo - editar o resto (ex.: só
    # renomear) não deveria obrigar a redigitar a senha do zero.
    if (d.get("senha") or "").strip():
        db.execute(
            "UPDATE bancos_monitorados SET nome=%s, host=%s, porta=%s, usuario=%s, senha=%s, banco=%s WHERE id=%s",
            (d["nome"].strip(), d["host"].strip(), porta, d["usuario"].strip(), d["senha"], d["banco"].strip(), banco_id),
        )
    else:
        db.execute(
            "UPDATE bancos_monitorados SET nome=%s, host=%s, porta=%s, usuario=%s, banco=%s WHERE id=%s",
            (d["nome"].strip(), d["host"].strip(), porta, d["usuario"].strip(), d["banco"].strip(), banco_id),
        )
    registrar("editar", "banco_monitorado", banco_id, f"Editou o banco monitorado \"{d['nome']}\"")
    return jsonify({"ok": True})


@bancos_bp.delete("/api/bancos/<int:banco_id>")
@perfis_permitidos("master")
def excluir_banco(banco_id):
    row = db.query_one("SELECT nome FROM bancos_monitorados WHERE id = %s", (banco_id,))
    if not row:
        return jsonify({"erro": "Banco não encontrado"}), 404
    db.execute("DELETE FROM bancos_monitorados WHERE id = %s", (banco_id,))
    registrar("excluir", "banco_monitorado", banco_id, f"Removeu o banco monitorado \"{row['nome']}\"")
    return jsonify({"ok": True})


@bancos_bp.post("/api/bancos/<banco_id>/testar")
@perfis_permitidos("master")
def testar_banco(banco_id):
    """Só tenta abrir e fechar uma conexão - não roda nenhuma query. Serve
    pra mostrar o selo verde/vermelho na tela sem esperar um backup inteiro."""
    if banco_id == "principal":
        try:
            db.query_one("SELECT 1")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "erro": str(e)})

    row = db.query_one("SELECT * FROM bancos_monitorados WHERE id = %s", (banco_id,))
    if not row:
        return jsonify({"erro": "Banco não encontrado"}), 404
    try:
        conn = _conectar(row)
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


def _montar_workbook(query_fn):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for titulo, colunas, sql in PLANILHAS_BACKUP:
        ws = wb.create_sheet(titulo[:31])
        ws.append(colunas)
        for linha in query_fn(sql):
            ws.append([linha.get(c, "") for c in colunas])
    return wb


@bancos_bp.get("/api/bancos/<banco_id>/backup/excel")
@perfis_permitidos("master")
def backup_banco_excel(banco_id):
    if banco_id == "principal":
        wb = _montar_workbook(db.query_all)
        nome_banco = "principal"
        registrar("exportar", "backup", None, "Baixou um backup completo dos dados do sistema (banco principal, via painel de Bancos de Dados)")
    else:
        row = db.query_one("SELECT * FROM bancos_monitorados WHERE id = %s", (banco_id,))
        if not row:
            return jsonify({"erro": "Banco não encontrado"}), 404
        try:
            conn = _conectar(row)
        except Exception as e:
            return jsonify({"erro": f"Não foi possível conectar nesse banco agora: {e}"}), 502
        try:
            cursor = conn.cursor(dictionary=True)

            def query_fn(sql):
                cursor.execute(sql)
                return cursor.fetchall()

            wb = _montar_workbook(query_fn)
        finally:
            conn.close()
        nome_banco = row["nome"]
        registrar("exportar", "banco_monitorado", row["id"], f"Baixou um backup completo do banco monitorado \"{row['nome']}\"")

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    slug = "".join(c if c.isalnum() else "_" for c in nome_banco.lower())
    nome_arquivo = f"backup_{slug}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buffer, as_attachment=True, download_name=nome_arquivo,
                      mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
