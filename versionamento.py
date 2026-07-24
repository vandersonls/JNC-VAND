import db


def salvar_versao(versoes_table, fk_col, fk_val, status_alvo, observacoes, usuario_id, extra_campos=None):
    """Salva uma versão como rascunho (editável, sobrescrita no lugar) ou a
    emite como definitiva. Cada "pai" (lista por desenho, ou projeto no caso
    de PQ/Compras) só tem um rascunho em aberto por vez: salvar rascunho de
    novo reaproveita a mesma linha e o mesmo número de versão, em vez de
    acumular uma versão nova a cada pausa no trabalho. Só quando emitido
    (status_alvo='salvo') a versão vira definitiva e imutável, como as demais.

    versoes_table/fk_col/extra_campos vêm sempre de literais fixos no código,
    nunca de entrada do usuário.

    Retorna (versao_id, numero_versao).
    """
    extra_campos = extra_campos or {}
    rascunho = db.query_one(
        f"SELECT id, versao FROM {versoes_table} WHERE {fk_col} = %s AND status = 'rascunho'",
        (fk_val,),
    )
    if rascunho:
        versao_id, numero_versao = rascunho["id"], rascunho["versao"]
        colunas_set = list(extra_campos.keys()) + ["status", "observacoes"]
        valores = list(extra_campos.values()) + [status_alvo, observacoes]
        sets = ", ".join(f"{c} = %s" for c in colunas_set)
        db.execute(f"UPDATE {versoes_table} SET {sets} WHERE id = %s", (*valores, versao_id))
    else:
        ultima = db.query_one(f"SELECT MAX(versao) AS mx FROM {versoes_table} WHERE {fk_col} = %s", (fk_val,))
        numero_versao = (ultima["mx"] or 0) + 1
        colunas = [fk_col, "versao", "status", "observacoes", "criado_por"] + list(extra_campos.keys())
        valores = [fk_val, numero_versao, status_alvo, observacoes, usuario_id] + list(extra_campos.values())
        placeholders = ", ".join(["%s"] * len(colunas))
        versao_id = db.execute(
            f"INSERT INTO {versoes_table} ({', '.join(colunas)}) VALUES ({placeholders})",
            tuple(valores),
        )
    return versao_id, numero_versao


def obter_rascunho(versoes_table, fk_col, fk_val):
    """Retorna a linha do rascunho em aberto do pai informado, ou None."""
    return db.query_one(
        f"SELECT * FROM {versoes_table} WHERE {fk_col} = %s AND status = 'rascunho'",
        (fk_val,),
    )
