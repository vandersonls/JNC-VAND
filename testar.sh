#!/usr/bin/env bash
# Roda os testes automáticos do NJC num banco SEPARADO (bmt_teste).
# Não mexe no banco local "bmt" nem no banco de produção.
# Uso (dentro da pasta do projeto):  bash testar.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# Usuário e senha do MySQL local (criados pelo organizar_linux.sh)
source .njc_local.env

# Instala o pytest no .venv na primeira vez
if ! .venv/bin/python -c "import pytest" 2>/dev/null; then
  echo "Instalando o pytest (ferramenta de testes) no .venv..."
  .venv/bin/pip install -q -r requirements-dev.txt
fi

# Na primeira vez, o usuário njc precisa de permissão no banco de teste.
if ! MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -u "$DB_USER" -e "CREATE DATABASE IF NOT EXISTS bmt_teste" 2>/dev/null; then
  echo "Dando ao usuário njc acesso ao banco de teste bmt_teste (só na primeira vez)."
  echo "O sudo pede sua senha do PC porque entra no MySQL como administrador."
  sudo mysql -e "GRANT ALL PRIVILEGES ON bmt_teste.* TO 'njc'@'localhost'; GRANT ALL PRIVILEGES ON bmt_teste.* TO 'njc'@'127.0.0.1'; FLUSH PRIVILEGES;"
fi

.venv/bin/python -m pytest -v "$@"
