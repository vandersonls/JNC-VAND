#!/usr/bin/env bash
# Para o NJC iniciado pelo iniciar_local.sh
# Vai para a pasta onde este script está (funciona em qualquer lugar)
cd "$(dirname "$(readlink -f "$0")")"
if [ -f .njc_servidor.pid ]; then
  PID="$(cat .njc_servidor.pid)"
  kill -TERM -- "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null || true
  rm -f .njc_servidor.pid
  echo "NJC parado."
else
  echo "O NJC não estava rodando (sem .njc_servidor.pid)."
fi
