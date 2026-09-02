"""Migra o molde fixo antigo (relatorio_templates/lista_por_desenho.xlsx,
o que ficava hardcoded em relatorios.py) para o novo sistema genérico de
moldes por cliente. Roda uma vez por banco (idempotente - se já existir um
molde 'lista_materiais' pro cliente, atualiza em vez de duplicar).

Uso: python migrar_template_gerdau.py "mysql://user:senha@host:porta/banco" <cliente_id>
"""
import json
import sys
from urllib.parse import urlparse

import mysql.connector

CAMINHO_ARQUIVO = "relatorio_templates/lista_por_desenho.xlsx"

# Tradução exata das constantes que existiam fixas em relatorios.py antes da
# generalização - preserva bit a bit o comportamento anterior.
MAPEAMENTO = {
    "abas": [
        {
            "origem": 0,  # Capa
            "campos": {
                "projeto": "V2", "subtitulo": "B4", "area": "B5", "disciplina": "B6", "titulo": "B7",
                "numero_cliente": "V4", "numero_projetista": "V7", "rev": "AG7",
            },
            "tabelas": [
                {
                    "fonte_dados": "revisoes",
                    "linha_inicial": 14, "linha_final_molde": 31, "linha_estilo": 20,
                    "colunas": [
                        ["rev", 2, 3], ["te", 4, 5], ["descricao", 6, 18], ["por", 19, 21],
                        ["ver", 22, 24], ["apr", 25, 27], ["aut", 28, 30], ["data", 31, 36],
                    ],
                    "col_direita_impressao": 36,
                    "canto_superior_impressao": "B2",
                }
            ],
        },
        {
            "origem": 1,  # Itens
            "campos": {
                "projeto": "W2", "subtitulo": "B4", "area": "B5", "disciplina": "B6", "titulo": "B7",
                "numero_cliente": "W4", "numero_projetista": "W7", "rev": "AG7",
                "referencia_desenho": "B9",
            },
            "tabelas": [
                {
                    "fonte_dados": "itens",
                    "linha_inicial": 11, "linha_final_molde": 42, "linha_estilo": 20,
                    "colunas": [
                        ["item", 2, 2], ["codigo", 3, 4], ["descricao", 5, 15], ["referencia", 16, 22],
                        ["complemento", 23, 27], ["unidade", 28, 29], ["quant_atual", 30, 32], ["quant_anterior", 33, 34],
                    ],
                    "col_direita_impressao": 34,
                    "canto_superior_impressao": "B2",
                }
            ],
        },
    ]
}


def montar_config(url):
    p = urlparse(url)
    return {
        "host": p.hostname, "port": p.port or 3306,
        "user": p.username, "password": p.password, "database": p.path.lstrip("/"),
    }


def main():
    if len(sys.argv) != 3:
        print('Uso: python migrar_template_gerdau.py "mysql://user:senha@host:porta/banco" <cliente_id>')
        sys.exit(1)
    conn = mysql.connector.connect(**montar_config(sys.argv[1]))
    cliente_id = int(sys.argv[2])
    cur = conn.cursor()

    cur.execute("SELECT razao_social FROM clientes WHERE id = %s", (cliente_id,))
    row = cur.fetchone()
    if not row:
        print(f"Cliente #{cliente_id} não encontrado nesse banco.")
        sys.exit(1)
    print(f"Migrando molde pro cliente #{cliente_id} ({row[0]})...")

    with open(CAMINHO_ARQUIVO, "rb") as f:
        conteudo = f.read()

    cur.execute(
        "SELECT id FROM clientes_templates WHERE cliente_id = %s AND tipo = 'lista_materiais'", (cliente_id,)
    )
    existente = cur.fetchone()
    mapeamento_json = json.dumps(MAPEAMENTO, ensure_ascii=False)
    if existente:
        cur.execute(
            "UPDATE clientes_templates SET nome_arquivo=%s, arquivo=%s, mapeamento=%s WHERE id=%s",
            ("lista_por_desenho.xlsx", conteudo, mapeamento_json, existente[0]),
        )
        print(f"Molde existente (#{existente[0]}) atualizado.")
    else:
        cur.execute(
            "INSERT INTO clientes_templates (cliente_id, tipo, nome_arquivo, arquivo, mapeamento) VALUES (%s,'lista_materiais',%s,%s,%s)",
            (cliente_id, "lista_por_desenho.xlsx", conteudo, mapeamento_json),
        )
        print(f"Molde criado (#{cur.lastrowid}).")
    conn.commit()
    print("Concluído.")


if __name__ == "__main__":
    main()
