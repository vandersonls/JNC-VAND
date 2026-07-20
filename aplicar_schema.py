"""Aplica schema.sql em um banco MySQL remoto (ex.: o MySQL do Railway).

Uso:
    python aplicar_schema.py "mysql://root:SENHA@HOST:PORTA/railway"

Pegue essa URL na aba Variables do serviço MySQL no Railway, na variável
MYSQL_PUBLIC_URL (para conectar de fora da rede interna do Railway).
Ignora os comandos "CREATE DATABASE" e "USE" do arquivo, pois o banco de
destino (ex.: "railway") já existe e já está selecionado pela própria URL.
"""
import re
import sys
from urllib.parse import urlparse

import mysql.connector


def main():
    if len(sys.argv) != 2:
        print('Uso: python aplicar_schema.py "mysql://user:senha@host:porta/banco"')
        sys.exit(1)

    url = urlparse(sys.argv[1])
    conn = mysql.connector.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.path.lstrip("/"),
        charset="utf8mb4",
    )
    cursor = conn.cursor()

    with open("schema.sql", encoding="utf-8") as f:
        sql = f.read()

    sql = re.sub(r"^--.*$", "", sql, flags=re.MULTILINE)
    comandos = [c.strip() for c in sql.split(";") if c.strip()]

    aplicados = 0
    for cmd in comandos:
        if cmd.upper().startswith("CREATE DATABASE") or cmd.upper().startswith("USE "):
            continue
        try:
            cursor.execute(cmd)
            if cursor.with_rows:
                cursor.fetchall()  # consome o resultset (ex.: dos "SELECT 1" usados como no-op) senão o proximo execute quebra
            conn.commit()
            aplicados += 1
        except mysql.connector.Error as e:
            print(f"ERRO em: {cmd[:70]!r} -> {e}")

    print(f"Concluído. {aplicados} comandos aplicados em '{url.path.lstrip('/')}'.")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
