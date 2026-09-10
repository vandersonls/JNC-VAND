"""Migra clientes_templates (molde por CLIENTE) -> projetos_templates
(molde por PROJETO). Um mesmo cliente pode ter templates diferentes em
projetos diferentes - compartilhar por cliente fazia um projeto "herdar"
por engano o molde já mapeado de outro projeto do mesmo cliente.

Idempotente: se a tabela clientes_templates não existir mais (já migrado,
ou banco novo criado direto com projetos_templates), não faz nada.

Antes de alterar qualquer coisa, salva um backup em JSON de cada linha de
clientes_templates (sem o blob do arquivo, só os metadados) num arquivo
local - histórico pra conferência, não é usado para restaurar automaticamente.

Uso: python migrar_templates_para_projeto.py "mysql://user:senha@host:porta/banco"

Se algum cliente tiver MAIS de um projeto, o script não adivinha pra qual
projeto vai o molde - precisa de uma entrada explícita em OVERRIDES (id da
linha de clientes_templates -> id do projeto), senão para com um erro
claro em vez de chutar."""
import json
import sys
from datetime import datetime
from urllib.parse import urlparse

import mysql.connector

# Preencher aqui quando o script parar pedindo (cliente com mais de um
# projeto). Já vem preenchido com o caso real conferido com o usuário em
# 2026-09-09: o molde da Jaguar (clientes_templates.id=3) pertence ao
# projeto "2 / dsdsd" (projetos.id=11) - o outro projeto da Jaguar
# ("01 / PROJETO AMPLIAÇÃO DA MINA FAINA", id=10) fica sem molde, que é o
# comportamento correto (nunca teve upload próprio).
OVERRIDES = {
    3: 11,
}


def conectar(url):
    p = urlparse(url)
    return mysql.connector.connect(
        host=p.hostname, port=p.port or 3306, user=p.username,
        password=p.password, database=p.path.lstrip("/"),
    )


def _nome_constraint(cur, tabela, tipo):
    cur.execute(
        "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_TYPE = %s",
        (tabela, tipo),
    )
    return [r["CONSTRAINT_NAME"] for r in cur.fetchall()]


def migrar(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SHOW TABLES LIKE 'clientes_templates'")
    if not cur.fetchall():
        print("Tabela clientes_templates não existe (já migrado, ou banco novo já usa projetos_templates) - nada a fazer.")
        return

    cur.execute("SELECT id, cliente_id, tipo, nome_arquivo, mapeamento IS NOT NULL AS mapeado, criado_em FROM clientes_templates")
    templates = cur.fetchall()
    print(f"{len(templates)} molde(s) encontrados em clientes_templates:")
    for t in templates:
        print(" ", {k: v for k, v in t.items()})

    backup_nome = f"backup_clientes_templates_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(backup_nome, "w", encoding="utf-8") as f:
        json.dump(templates, f, default=str, ensure_ascii=False, indent=2)
    print(f"Backup dos metadados (sem o arquivo em si) salvo em {backup_nome}")

    projeto_por_template = {}
    for t in templates:
        tid, cliente_id = t["id"], t["cliente_id"]
        if tid in OVERRIDES:
            projeto_por_template[tid] = OVERRIDES[tid]
            continue
        cur.execute("SELECT id, codigo, nome FROM projetos WHERE cliente_id = %s", (cliente_id,))
        projetos = cur.fetchall()
        if len(projetos) != 1:
            raise SystemExit(
                f"Template id={tid} (cliente_id={cliente_id}) tem {len(projetos)} projeto(s) associados: {projetos}. "
                f"Adicione um override explícito em OVERRIDES (linha {tid} -> id do projeto certo) e rode de novo."
            )
        projeto_por_template[tid] = projetos[0]["id"]

    print("\nMapeamento a aplicar (id do molde -> id do projeto):", projeto_por_template)

    fk_cliente = _nome_constraint(cur, "clientes_templates", "FOREIGN KEY")
    uq_cliente = _nome_constraint(cur, "clientes_templates", "UNIQUE")

    cur.execute("ALTER TABLE clientes_templates RENAME TO projetos_templates")
    cur.execute("ALTER TABLE projetos_templates ADD COLUMN projeto_id INT NULL AFTER cliente_id")
    for tid, projeto_id in projeto_por_template.items():
        cur.execute("UPDATE projetos_templates SET projeto_id = %s WHERE id = %s", (projeto_id, tid))
    cur.execute("ALTER TABLE projetos_templates MODIFY projeto_id INT NOT NULL")
    for nome in fk_cliente:
        cur.execute(f"ALTER TABLE projetos_templates DROP FOREIGN KEY `{nome}`")
    for nome in uq_cliente:
        cur.execute(f"ALTER TABLE projetos_templates DROP INDEX `{nome}`")
    cur.execute("ALTER TABLE projetos_templates DROP COLUMN cliente_id")
    cur.execute(
        "ALTER TABLE projetos_templates ADD CONSTRAINT fk_template_projeto "
        "FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE"
    )
    cur.execute("ALTER TABLE projetos_templates ADD UNIQUE KEY uq_projeto_tipo (projeto_id, tipo)")
    conn.commit()
    print("\nMigração concluída - clientes_templates agora é projetos_templates, vinculada por projeto_id.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('Uso: python migrar_templates_para_projeto.py "mysql://user:senha@host:porta/banco"')
    conn = conectar(sys.argv[1])
    try:
        migrar(conn)
    finally:
        conn.close()
