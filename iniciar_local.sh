#!/usr/bin/env bash
# Sobe o NJC localmente em http://localhost:5000 (em segundo plano).
# Parar: bash parar_local.sh   |   Ver o log: tail -f servidor.log
set -euo pipefail
# Vai para a pasta onde este script está (funciona em qualquer lugar)
cd "$(dirname "$(readlink -f "$0")")"

if [ -f .njc_servidor.pid ] && kill -0 "$(cat .njc_servidor.pid)" 2>/dev/null; then
  echo "O NJC já está rodando (PID $(cat .njc_servidor.pid)): http://localhost:5000"
  exit 0
fi

# Senha e usuário do banco LOCAL (ver README: "Rodar no seu computador")
if [ ! -f .njc_local.env ]; then
  echo "Falta o arquivo .njc_local.env (copie de .env.example e preencha). Veja o README."
  exit 1
fi
source .njc_local.env
# Modo debug do Flask: recarrega sozinho ao salvar um arquivo. O servidor só
# aceita conexões deste computador (127.0.0.1), então o debug não fica exposto.
export FLASK_DEBUG=1

# setsid: o servidor fica num grupo próprio, para o parar_local.sh encerrar tudo junto
setsid nohup .venv/bin/python app.py > servidor.log 2>&1 &
echo $! > .njc_servidor.pid

echo "Iniciando..."
for _ in $(seq 1 20); do
  if curl -fsS http://localhost:5000/health >/dev/null 2>&1; then
    echo "NJC rodando: http://localhost:5000  (health: $(curl -s http://localhost:5000/health))"
    exit 0
  fi
  sleep 1
done
echo "O servidor não respondeu em 20 s. Últimas linhas do log:"
tail -n 30 servidor.log
exit 1
