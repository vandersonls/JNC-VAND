# NJC — Gestão de materiais para projetos de engenharia elétrica

Sistema web para catálogo de materiais, Lista por Desenho, Planilha de
Quantidades (PQ), Lista de Compras e geração dos Excel/PDF de cada projeto.
Feito em Flask (Python) + MySQL; a tela é uma página única em JavaScript que
conversa com a API em `/api/...`.

Produção: <https://jnc-vand-production.up.railway.app> (Railway, publicado a
partir da branch `master` deste repositório).

## Estrutura

| Onde | O que é |
| --- | --- |
| `app.py` | Ponto de entrada: cria o app Flask e registra os módulos |
| `*.py` na raiz | Um módulo por área do sistema (`materiais.py`, `projetos.py`, `lista_pq.py`, `lista_compras.py`, `relatorios.py`, `auth.py`...) |
| `templates/`, `static/` | A tela (HTML, CSS e o `app.js`) |
| `relatorio_templates/` | Modelos de Excel usados nos relatórios |
| `banco/schema.sql` | Esquema completo do banco, com migrações que podem ser reaplicadas |
| `scripts/` | Utilitários rodados à mão: `seed.py`, `aplicar_schema.py`, `migrar_templates_para_projeto.py` (histórico) |
| `tests/` | Testes automáticos (rodam num banco separado, `bmt_teste`) |
| `iniciar_local.sh`, `parar_local.sh`, `testar.sh` | Atalhos para o dia a dia no Linux |

## Rodar no seu computador (Linux)

Primeira vez:

```bash
sudo apt install git curl python3-venv python3-pip mysql-server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Usuário do MySQL só para o projeto (troque SENHA por uma sua)
sudo mysql < banco/schema.sql
sudo mysql -e "CREATE USER 'njc'@'localhost' IDENTIFIED BY 'SENHA';
               CREATE USER 'njc'@'127.0.0.1' IDENTIFIED BY 'SENHA';
               GRANT ALL ON bmt.* TO 'njc'@'localhost';
               GRANT ALL ON bmt.* TO 'njc'@'127.0.0.1';"

cp .env.example .njc_local.env   # e coloque a SENHA nele
chmod 600 .njc_local.env
source .njc_local.env && .venv/bin/python scripts/seed.py   # cria o login local admin@bmt.com
```

O `.njc_local.env` fica só no seu computador (está no `.gitignore`).

Dia a dia:

| Comando | O que faz |
| --- | --- |
| `bash iniciar_local.sh` | Liga o sistema em <http://localhost:5000> |
| `bash parar_local.sh` | Desliga |
| `bash testar.sh` | Roda os testes automáticos |
| `tail -f servidor.log` | Mostra o que o servidor está fazendo |

O servidor local só aceita conexões do próprio computador.

## Publicar

1. `bash testar.sh` — tudo tem que passar.
2. `git status` e `git diff` — conferir o que vai no commit (nada de senhas, `.njc_local.env` ou URL de banco).
3. `git add ...`, `git commit -m "o que mudou"`, `git push vanderson master`.
4. O Railway publica sozinho; conferir `/health` no endereço de produção.
5. Se `banco/schema.sql` mudou, aplicar no banco de produção:
   `.venv/bin/python scripts/aplicar_schema.py "<MYSQL_PUBLIC_URL>"`
   (a URL fica no Railway, em Variables do serviço MySQL; nunca salve em arquivo).

## Variáveis de ambiente

Veja `.env.example`. Em produção, o Railway fornece `MYSQL_URL`; `SECRET_KEY`
precisa estar definida lá.
