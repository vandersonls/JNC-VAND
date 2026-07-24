import json

from flask import Blueprint, request, jsonify
from flask_login import current_user

import db
from auth import perfis_permitidos

auditoria_bp = Blueprint("auditoria", __name__)


def _serializar(dados):
    if dados is None:
        return None
    return json.dumps(dados, default=str, ensure_ascii=False)


def registrar(acao, entidade, entidade_id, descricao, antes=None, depois=None):
    """Grava um evento de auditoria. Nunca deve interromper a operação principal caso falhe."""
    try:
        usuario_id = current_user.id if current_user.is_authenticated else None
        usuario_nome = current_user.nome if current_user.is_authenticated else "Sistema"
        db.execute(
            """INSERT INTO auditoria (usuario_id, usuario_nome, acao, entidade, entidade_id, descricao, dados_antes, dados_depois)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (usuario_id, usuario_nome, acao, entidade, entidade_id, descricao, _serializar(antes), _serializar(depois)),
        )
    except Exception as e:  # noqa: BLE001 - auditoria não pode derrubar a requisição principal
        print(f"[auditoria] falha ao registrar evento: {e}")


@auditoria_bp.get("/api/auditoria")
@perfis_permitidos("master", "administrador")
def listar_auditoria():
    entidade = request.args.get("entidade", "").strip()
    usuario_id = request.args.get("usuario_id", "").strip()
    busca = request.args.get("q", "").strip()
    limite = min(int(request.args.get("limite", 50)), 200)
    offset = max(int(request.args.get("offset", 0)), 0)

    condicoes, params = [], []
    if entidade:
        condicoes.append("entidade = %s")
        params.append(entidade)
    if usuario_id:
        condicoes.append("usuario_id = %s")
        params.append(usuario_id)
    if busca:
        condicoes.append("(descricao LIKE %s OR usuario_nome LIKE %s)")
        params.extend([f"%{busca}%", f"%{busca}%"])

    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.query_all(
        f"""SELECT id, usuario_id, usuario_nome, acao, entidade, entidade_id, descricao,
                   dados_antes, dados_depois, criado_em
            FROM auditoria {where}
            ORDER BY criado_em DESC
            LIMIT %s OFFSET %s""",
        (*params, limite, offset),
    )
    total = db.query_one(f"SELECT COUNT(*) AS total FROM auditoria {where}", tuple(params))
    return jsonify({"itens": rows, "total": total["total"]})


@auditoria_bp.get("/api/auditoria/entidades")
@perfis_permitidos("master", "administrador")
def listar_entidades():
    rows = db.query_all("SELECT DISTINCT entidade FROM auditoria ORDER BY entidade")
    return jsonify([r["entidade"] for r in rows])
