"""Testes do caminho principal do NJC: se algum destes quebrar depois de uma
mudança no código, a mudança estragou algo que os usuários usam todo dia."""
from conftest import EMAIL_MASTER, SENHA_MASTER


# --- Sistema no ar --------------------------------------------------------

def test_health_responde_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_pagina_inicial_carrega(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"app.js" in resp.data


# --- Login ----------------------------------------------------------------

def test_login_com_senha_errada_e_recusado(client):
    resp = client.post("/api/login", json={"email": EMAIL_MASTER, "senha": "errada"})
    assert resp.status_code == 401


def test_login_aceita_maiusculas_no_usuario(client):
    resp = client.post("/api/login", json={"email": EMAIL_MASTER.upper(), "senha": SENHA_MASTER})
    assert resp.status_code == 200
    assert resp.get_json()["usuario"]["perfil"] == "master"
    client.post("/api/logout")


def test_rotas_protegidas_exigem_login(client):
    assert client.get("/api/projetos").status_code == 401
    assert client.get("/api/me").get_json() == {"usuario": None}


def test_bloqueia_conta_apos_8_senhas_erradas(client, banco):
    from werkzeug.security import generate_password_hash

    banco(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (%s, %s, %s, 'visualizador')",
        ("Alvo", "alvo.bloqueio", generate_password_hash("Certa1234")),
    )
    for _ in range(8):
        assert client.post("/api/login", json={"email": "alvo.bloqueio", "senha": "x"}).status_code == 401
    resp = client.post("/api/login", json={"email": "alvo.bloqueio", "senha": "Certa1234"})
    assert resp.status_code == 429


# --- Cadastro de projeto e listas -------------------------------------------

def _criar_base(c):
    """Cria área, cliente, 2 materiais e um projeto; devolve os ids."""
    area = c.post("/api/areas", json={"nome": "Área Teste"})
    if area.status_code == 409:  # já criada por outro teste
        area_id = [a for a in c.get("/api/areas").get_json() if a["nome"] == "Área Teste"][0]["id"]
    else:
        assert area.status_code == 201, area.get_json()
        area_id = area.get_json()["id"]

    cliente = c.post("/api/clientes", json={"razao_social": "Cliente Teste"})
    assert cliente.status_code == 201, cliente.get_json()
    cliente_id = cliente.get_json()["id"]

    materiais = []
    for codigo in ("MAT-001", "MAT-002"):
        resp = c.post("/api/materiais", json={
            "codigo": f"{codigo}-{cliente_id}", "descricao": f"Cabo {codigo}", "fabricante": "Fab",
            "bitola": "2,5mm", "unidade": "m", "area_id": area_id,
        })
        assert resp.status_code == 201, resp.get_json()
        materiais.append(resp.get_json()["id"])

    projeto = c.post("/api/projetos", json={
        "codigo": f"PRJ-{cliente_id}", "nome": "Projeto Teste", "cliente_id": cliente_id, "area_id": area_id,
    })
    assert projeto.status_code == 201, projeto.get_json()
    return projeto.get_json()["id"], materiais


def test_criar_projeto_aparece_na_lista(logado):
    projeto_id, _ = _criar_base(logado)
    ids = [p["id"] for p in logado.get("/api/projetos").get_json()]
    assert projeto_id in ids


def test_codigo_de_projeto_repetido_e_recusado(logado):
    projeto_id, _ = _criar_base(logado)
    projeto = logado.get(f"/api/projetos/{projeto_id}").get_json()
    resp = logado.post("/api/projetos", json={
        "codigo": projeto["codigo"], "nome": "Outro", "cliente_id": projeto["cliente_id"], "area_id": projeto["area_id"],
    })
    assert resp.status_code == 409
    assert "Já existe um projeto" in resp.get_json()["erro"]


def test_lista_por_desenho_exige_tipo_de_emissao_ao_emitir(logado):
    projeto_id, (m1, _) = _criar_base(logado)
    resp = logado.post(f"/api/projetos/{projeto_id}/listas", json={
        "numero_desenho": "DES-01", "itens": [{"material_id": m1, "quantidade": 10}],
    })
    assert resp.status_code == 400


def test_fluxo_completo_desenho_pq_compras(logado, banco):
    """Lista por Desenho -> base da PQ -> PQ emitida -> Lista de Compras."""
    projeto_id, (m1, m2) = _criar_base(logado)

    # Duas listas por desenho, ambas com o material 1: a base da PQ soma.
    for numero, itens in (("DES-01", [(m1, 10), (m2, 4)]), ("DES-02", [(m1, 5)])):
        resp = logado.post(f"/api/projetos/{projeto_id}/listas", json={
            "numero_desenho": numero, "tipo_emissao": "A",
            "itens": [{"material_id": m, "quantidade": q} for m, q in itens],
        })
        assert resp.status_code == 201, resp.get_json()

    base = logado.post(f"/api/projetos/{projeto_id}/lista-pq/base", json={}).get_json()
    por_material = {linha["material_id"]: float(linha["quantidade_base"]) for linha in base}
    assert por_material == {m1: 15.0, m2: 4.0}

    # PQ como rascunho: não vira a versão atual do projeto.
    itens_pq = [{"material_id": m1, "quantidade_base": 15, "percentual": 10},
                {"material_id": m2, "quantidade_base": 4, "percentual": 0}]
    resp = logado.post(f"/api/projetos/{projeto_id}/lista-pq", json={"status": "rascunho", "itens": itens_pq})
    assert resp.status_code == 201 and resp.get_json()["versao"] == 1
    assert logado.get(f"/api/projetos/{projeto_id}/lista-pq").get_json()["versao"] is None

    # Emitir reaproveita o rascunho (mesma versão 1) e calcula +10%.
    resp = logado.post(f"/api/projetos/{projeto_id}/lista-pq", json={"status": "salvo", "itens": itens_pq})
    assert resp.status_code == 201 and resp.get_json()["versao"] == 1
    pq = logado.get(f"/api/projetos/{projeto_id}/lista-pq").get_json()
    atualizadas = {i["material_id"]: float(i["quantidade_atualizada"]) for i in pq["itens"]}
    assert atualizadas[m1] == 16.5 and atualizadas[m2] == 4.0
    origens = banco("SELECT numero_desenho FROM lista_pq_origens WHERE pq_versao_id = %s", (pq["versao"]["id"],))
    assert sorted(o["numero_desenho"] for o in origens) == ["DES-01", "DES-02"]

    # Nova emissão cria a versão 2; a 1 continua intacta.
    resp = logado.post(f"/api/projetos/{projeto_id}/lista-pq", json={"status": "salvo", "itens": itens_pq[:1]})
    assert resp.get_json()["versao"] == 2
    versoes = logado.get(f"/api/projetos/{projeto_id}/lista-pq/versoes").get_json()
    assert sorted(v["versao"] for v in versoes) == [1, 2]

    # Lista de Compras emitida fica ligada à PQ atual.
    resp = logado.post(f"/api/projetos/{projeto_id}/lista-compras", json={
        "status": "salvo", "itens": [{"material_id": m1, "quantidade": 17}],
    })
    assert resp.status_code == 201, resp.get_json()
    compras = banco("SELECT v.pq_versao_id, i.quantidade FROM lista_compras_versoes v "
                    "JOIN lista_compras_itens i ON i.versao_id = v.id WHERE v.projeto_id = %s", (projeto_id,))
    pq_atual = logado.get(f"/api/projetos/{projeto_id}/lista-pq").get_json()["versao"]["id"]
    assert compras[0]["pq_versao_id"] == pq_atual and float(compras[0]["quantidade"]) == 17.0


def test_pq_e_compras_vazias_sao_recusadas(logado):
    projeto_id, _ = _criar_base(logado)
    assert logado.post(f"/api/projetos/{projeto_id}/lista-pq", json={"itens": []}).status_code == 400
    assert logado.post(f"/api/projetos/{projeto_id}/lista-compras", json={"itens": []}).status_code == 400


def test_editar_projeto_para_codigo_de_outro_e_recusado(logado):
    projeto_a, _ = _criar_base(logado)
    projeto_b, _ = _criar_base(logado)
    a = logado.get(f"/api/projetos/{projeto_a}").get_json()
    b = logado.get(f"/api/projetos/{projeto_b}").get_json()
    resp = logado.put(f"/api/projetos/{projeto_b}", json={
        "codigo": a["codigo"], "nome": b["nome"], "cliente_id": b["cliente_id"], "area_id": b["area_id"],
    })
    assert resp.status_code == 409
    # Manter o próprio código ao editar continua permitido.
    resp = logado.put(f"/api/projetos/{projeto_b}", json={
        "codigo": b["codigo"], "nome": "Nome novo", "cliente_id": b["cliente_id"], "area_id": b["area_id"],
    })
    assert resp.status_code == 200
