"""Registro de erro em arquivo.

Por que existe: quando uma rota estoura, o traceback ia só para o console do
processo (`print_exc`). Fechada a janela preta, ou rodando como servico, o
motivo do 500 desaparecia - sobrava a mensagem generica da tela, que nao diz
nada a quem vai consertar. Aqui o mesmo traceback tambem vai para
`logs/erros.log`, que o `.gitignore` ja ignora (`*.log`).

O arquivo guarda data/hora, metodo, caminho, quem estava logado e o
traceback. Nao guarda corpo de requisicao nem cookie, para nao parar senha
nem dado de cliente num arquivo de log.
"""

import os
import traceback
from datetime import datetime

CAMINHO_LOG = os.path.join(os.path.dirname(__file__), "logs", "erros.log")

SEPARADOR = "=" * 78


def _quem():
    """Identifica o usuario logado, se houver. Fora de uma requisicao (ou sem
    login) devolve '-', em vez de estourar outro erro dentro do registrador."""
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return f"{current_user.id} ({current_user.nome})"
    except Exception:
        pass
    return "-"


def _onde():
    try:
        from flask import request
        return f"{request.method} {request.path}"
    except Exception:
        return "-"


def registrar(origem=""):
    """Grava o traceback da excecao que esta sendo tratada agora.

    Chamado de dentro de um `except`. Nunca levanta: um erro no registrador
    nao pode virar um segundo erro em cima do primeiro.
    """
    try:
        os.makedirs(os.path.dirname(CAMINHO_LOG), exist_ok=True)
        with open(CAMINHO_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{SEPARADOR}\n")
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {_onde()}\n")
            f.write(f"usuario: {_quem()}\n")
            if origem:
                f.write(f"origem: {origem}\n")
            f.write(SEPARADOR + "\n")
            f.write(traceback.format_exc())
            f.flush()
    except Exception:
        # Log quebrado nao pode derrubar a requisicao.
        pass
    # Mantem o comportamento antigo: o traceback continua aparecendo no
    # console de quem esta com o app aberto.
    traceback.print_exc()


def registrar_erro_nao_tratado(app):
    """Liga o registrador em qualquer excecao que escape das rotas.

    O Flask continua tratando o erro como antes (em debug mostra o debugger,
    em producao devolve 500) - este handler so registra e repassa.
    """
    @app.errorhandler(Exception)
    def _registrar(e):
        from werkzeug.exceptions import HTTPException
        # 404, 403, 401 e companhia nao sao defeito: passam direto.
        if isinstance(e, HTTPException):
            return e
        registrar("excecao nao tratada numa rota")
        raise e
