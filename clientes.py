from flask import Blueprint, request, jsonify
from flask_login import login_required

import db
from auth import perfis_permitidos

clientes_bp = Blueprint("clientes", __name__)

CAMPOS = ["razao_social", "nome_fantasia", "cnpj_cpf", "contato", "telefone", "email", "endereco"]


@clientes_bp.get("/api/clientes")
@login_required
def listar_clientes():
    busca = request.args.get("q", "").strip()
    if busca:
        like = f"%{busca}%"
        rows = db.query_all(
            """SELECT * FROM clientes WHERE ativo = 1
               AND (razao_social LIKE %s OR nome_fantasia LIKE %s OR cnpj_cpf LIKE %s)
               ORDER BY razao_social""",
            (like, like, like),
        )
    else:
        rows = db.query_all("SELECT * FROM clientes WHERE ativo = 1 ORDER BY razao_social")
    return jsonify(rows)


@clientes_bp.post("/api/clientes")
@perfis_permitidos("master", "administrador")
def criar_cliente():
    data = request.get_json(force=True) or {}
    if not data.get("razao_social"):
        return jsonify({"erro": "Razão social é obrigatória"}), 400
    novo_id = db.execute(
        f"""INSERT INTO clientes ({', '.join(CAMPOS)}) VALUES ({', '.join(['%s'] * len(CAMPOS))})""",
        tuple(data.get(c, "") for c in CAMPOS),
    )
    return jsonify({"id": novo_id}), 201


@clientes_bp.put("/api/clientes/<int:cliente_id>")
@perfis_permitidos("master", "administrador")
def editar_cliente(cliente_id):
    data = request.get_json(force=True) or {}
    if not data.get("razao_social"):
        return jsonify({"erro": "Razão social é obrigatória"}), 400
    sets = ", ".join(f"{c}=%s" for c in CAMPOS)
    db.execute(
        f"UPDATE clientes SET {sets} WHERE id=%s",
        (*[data.get(c, "") for c in CAMPOS], cliente_id),
    )
    return jsonify({"ok": True})


@clientes_bp.delete("/api/clientes/<int:cliente_id>")
@perfis_permitidos("master", "administrador")
def excluir_cliente(cliente_id):
    db.execute("UPDATE clientes SET ativo = 0 WHERE id = %s", (cliente_id,))
    return jsonify({"ok": True})
