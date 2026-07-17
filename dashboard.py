from datetime import date, timedelta

from flask import Blueprint, jsonify
from flask_login import login_required

import db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/api/dashboard/resumo")
@login_required
def resumo():
    projetos_por_status = db.query_all(
        "SELECT status, COUNT(*) AS total FROM projetos GROUP BY status"
    )

    top_fabricantes = db.query_all(
        """SELECT COALESCE(NULLIF(TRIM(fabricante), ''), 'Não informado') AS fabricante, COUNT(*) AS total
           FROM materiais
           WHERE ativo = 1
           GROUP BY fabricante
           ORDER BY total DESC
           LIMIT 6"""
    )

    atividade_rows = db.query_all(
        """SELECT DATE(criado_em) AS dia, COUNT(*) AS total
           FROM auditoria
           WHERE criado_em >= %s
           GROUP BY DATE(criado_em)""",
        (date.today() - timedelta(days=13),),
    )
    contagem_por_dia = {str(r["dia"]): r["total"] for r in atividade_rows}
    atividade_por_dia = [
        {"data": str(d), "total": contagem_por_dia.get(str(d), 0)}
        for d in (date.today() - timedelta(days=i) for i in range(13, -1, -1))
    ]

    return jsonify({
        "projetos_por_status": projetos_por_status,
        "top_fabricantes": top_fabricantes,
        "atividade_por_dia": atividade_por_dia,
    })
