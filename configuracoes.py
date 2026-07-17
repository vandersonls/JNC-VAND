from flask import Blueprint, request, jsonify
from flask_login import login_required

import db
from auth import perfis_permitidos

config_bp = Blueprint("config", __name__)


@config_bp.get("/api/configuracoes")
@login_required
def listar_configuracoes():
    rows = db.query_all("SELECT chave, valor, descricao FROM configuracoes ORDER BY chave")
    return jsonify(rows)


@config_bp.put("/api/configuracoes")
@perfis_permitidos("master", "administrador")
def atualizar_configuracoes():
    data = request.get_json(force=True) or {}
    for chave, valor in data.items():
        db.execute(
            "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE valor = VALUES(valor)",
            (chave, valor),
        )
    return jsonify({"ok": True})
