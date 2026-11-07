"""Repositório: a única camada que fala SQL.

Toda função recebe uma `sqlite3.Connection` aberta (não abre conexão).
Devolve `dict` (nunca `sqlite3.Row`) — a camada acima não deve saber que
existe SQLite. Sem regra de negócio: comparações, cache e decisões vivem
no serviço, não aqui.
"""

from __future__ import annotations

import sqlite3
from typing import Any

# Campos de `observacao` que o adapter de fonte entrega já normalizados.
# Se o schema ganhar uma coluna nova, adicione aqui — sem isso, o campo
# novo sempre virá nulo mesmo quando o adapter o enviar em `dados`.
_CAMPOS_OBSERVACAO: tuple[str, ...] = (
    "razao_social",
    "nome_fantasia",
    "situacao",
    "data_situacao",
    "porte",
    "cnae_codigo",
    "cnae_descricao",
    "municipio",
    "uf",
    "capital_centavos",
    "qtd_socios",
)


def _row_para_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Converte ``sqlite3.Row`` em ``dict``; devolve ``None`` se a linha for nula."""
    if row is None:
        return None
    # ``sqlite3.Row`` não é ``dict``: iterar direto sobre ele devolve os
    # valores, não as chaves. Por isso a lista de chaves é extraída antes.
    keys = row.keys()
    return {k: row[k] for k in keys}


def inserir_empresa_se_nao_existe(con: sqlite3.Connection, cnpj: str, agora: str) -> None:
    """Cadastra a empresa se ainda não existir.

    Idempotente: chamar duas vezes com o mesmo ``cnpj`` não duplica. Usa
    ``ON CONFLICT(cnpj) DO NOTHING`` — não ``INSERT OR IGNORE`` — para que
    somente a duplicidade de PK seja ignorada. Violação de ``CHECK`` (ex.:
    ``cnpj`` com tamanho errado) continua estourando, o que é o correto.
    """
    con.execute(
        "INSERT INTO empresa (cnpj, primeira_consulta, ultima_consulta) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(cnpj) DO NOTHING",
        (cnpj, agora, agora),
    )


def inserir_observacao(
    con: sqlite3.Connection,
    *,
    cnpj: str,
    dados: dict[str, Any],
    fonte: str,
    coletado_em: str,
    bruto_json: str,
) -> int:
    """Grava uma observação append-only e devolve o ``id`` gerado.

    ``dados`` deve trazer os campos já normalizados pelo adapter de fonte
    (razao_social, situacao, etc.). Campos ausentes viram ``NULL``. O
    ``bruto_json`` deve conter a resposta inteira da API como veio.
    """
    colunas = ["cnpj", "coletado_em", "fonte", "bruto_json", *_CAMPOS_OBSERVACAO]
    valores: list[Any] = [cnpj, coletado_em, fonte, bruto_json]
    valores.extend(dados.get(campo) for campo in _CAMPOS_OBSERVACAO)

    placeholders = ", ".join("?" for _ in colunas)
    sql = f"INSERT INTO observacao ({', '.join(colunas)}) VALUES ({placeholders})"
    cur = con.execute(sql, valores)
    return cur.lastrowid  # type: ignore[return-value]


def observacoes_por_cnpj(con: sqlite3.Connection, cnpj: str) -> list[dict[str, Any]]:
    """Todas as observações de uma empresa, em ordem cronológica.

    Ordena por ``(coletado_em, id)`` — ``coletado_em`` sozinho pode empatar
    quando duas coletas caem no mesmo segundo; ``id`` desempata.
    """
    rows = con.execute(
        "SELECT * FROM observacao WHERE cnpj = ? ORDER BY coletado_em, id",
        (cnpj,),
    ).fetchall()
    return [_row_para_dict(r) for r in rows]  # type: ignore[misc]


def observacao_mais_nova(con: sqlite3.Connection, cnpj: str) -> dict[str, Any] | None:
    """A observação mais recente da empresa, ou ``None`` se ainda não houver.

    Mesmo desempate de `observacoes_por_cnpj`: ``id`` decide quando duas
    coletas caem no mesmo segundo.
    """
    row = con.execute(
        "SELECT * FROM observacao WHERE cnpj = ? ORDER BY coletado_em DESC, id DESC LIMIT 1",
        (cnpj,),
    ).fetchone()
    return _row_para_dict(row)


def atualizar_ultima_consulta(con: sqlite3.Connection, cnpj: str, agora: str) -> None:
    """Atualiza ``empresa.ultima_consulta``. Não toca em ``primeira_consulta``."""
    con.execute(
        "UPDATE empresa SET ultima_consulta = ? WHERE cnpj = ?",
        (agora, cnpj),
    )


def registrar_falha(
    con: sqlite3.Connection,
    *,
    cnpj: str,
    fonte: str,
    motivo: str,
    ocorrido_em: str,
) -> None:
    """Registra falha de tentativa de coleta.

    Não exige empresa cadastrada: a falha pode ocorrer antes do primeiro
    sucesso de coleta (ex.: a fonte caiu no meio da primeira consulta).
    """
    con.execute(
        "INSERT INTO falha_coleta (cnpj, ocorrido_em, fonte, motivo) VALUES (?, ?, ?, ?)",
        (cnpj, ocorrido_em, fonte, motivo),
    )


def empresa_por_cnpj(con: sqlite3.Connection, cnpj: str) -> dict[str, Any] | None:
    """Devolve a empresa como ``dict`` ou ``None`` se não existir."""
    row = con.execute("SELECT * FROM empresa WHERE cnpj = ?", (cnpj,)).fetchone()
    return _row_para_dict(row)
