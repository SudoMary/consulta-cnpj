"""Repositório: a única camada que fala SQL.

Toda função recebe uma conexão aberta do SQLAlchemy: não abre conexão nem faz
commit, porque a transação é de quem chama. Devolve `dict`, para que a camada
acima não dependa do banco. O SQL é o mesmo no SQLite e no PostgreSQL, com
parâmetros nomeados (``:cnpj``), nunca com o valor dentro do texto. Sem regra
de negócio: comparações, cache e decisões vivem no serviço.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

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


def inserir_empresa_se_nao_existe(con: Connection, cnpj: str, agora: str) -> None:
    """Cadastra a empresa se ainda não existir.

    Idempotente: chamar duas vezes com o mesmo ``cnpj`` não duplica. Usa
    ``ON CONFLICT (cnpj) DO NOTHING`` para que somente a duplicidade de PK seja
    ignorada. Violação de ``CHECK`` (ex.: ``cnpj`` com tamanho errado) continua
    estourando, o que é o correto.
    """
    con.execute(
        text(
            "INSERT INTO empresa (cnpj, primeira_consulta, ultima_consulta) "
            "VALUES (:cnpj, :agora, :agora) "
            "ON CONFLICT (cnpj) DO NOTHING"
        ),
        {"cnpj": cnpj, "agora": agora},
    )


def inserir_observacao(
    con: Connection,
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
    valores: dict[str, Any] = {
        "cnpj": cnpj,
        "coletado_em": coletado_em,
        "fonte": fonte,
        "bruto_json": bruto_json,
    }
    valores.update({campo: dados.get(campo) for campo in _CAMPOS_OBSERVACAO})

    # Os nomes das colunas vêm da tupla fixa acima, nunca de quem chama;
    # os valores vão como parâmetros.
    colunas = ", ".join(valores)
    marcadores = ", ".join(f":{coluna}" for coluna in valores)
    sql = f"INSERT INTO observacao ({colunas}) VALUES ({marcadores}) RETURNING id"
    return con.execute(text(sql), valores).scalar_one()


def observacoes_por_cnpj(con: Connection, cnpj: str) -> list[dict[str, Any]]:
    """Todas as observações de uma empresa, em ordem cronológica.

    Ordena por ``(coletado_em, id)`` — ``coletado_em`` sozinho pode empatar
    quando duas coletas caem no mesmo segundo; ``id`` desempata.
    """
    linhas = con.execute(
        text("SELECT * FROM observacao WHERE cnpj = :cnpj ORDER BY coletado_em, id"),
        {"cnpj": cnpj},
    ).mappings()
    return [dict(linha) for linha in linhas]


def observacao_mais_nova(con: Connection, cnpj: str) -> dict[str, Any] | None:
    """A observação mais recente da empresa, ou ``None`` se ainda não houver.

    Mesmo desempate de `observacoes_por_cnpj`: ``id`` decide quando duas
    coletas caem no mesmo segundo.
    """
    linha = (
        con.execute(
            text(
                "SELECT * FROM observacao WHERE cnpj = :cnpj "
                "ORDER BY coletado_em DESC, id DESC LIMIT 1"
            ),
            {"cnpj": cnpj},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def observacoes_mais_novas(con: Connection) -> list[dict[str, Any]]:
    """A observação mais recente de cada empresa, em ordem de CNPJ.

    Uma linha por empresa, com o desempate de `observacao_mais_nova`, mais a
    coluna ``acompanhando`` da empresa.
    """
    linhas = con.execute(
        text(
            "SELECT o.*, e.acompanhando FROM observacao o "
            "JOIN empresa e ON e.cnpj = o.cnpj "
            "WHERE o.id = ("
            "SELECT o2.id FROM observacao o2 WHERE o2.cnpj = o.cnpj "
            "ORDER BY o2.coletado_em DESC, o2.id DESC LIMIT 1"
            ") ORDER BY o.cnpj"
        )
    ).mappings()
    return [dict(linha) for linha in linhas]


def cnpjs_com_historico(con: Connection) -> list[str]:
    """CNPJs com mais de uma observação: só neles pode haver mudança."""
    return list(
        con.execute(
            text("SELECT cnpj FROM observacao GROUP BY cnpj HAVING COUNT(*) > 1 ORDER BY cnpj")
        ).scalars()
    )


def atualizar_ultima_consulta(con: Connection, cnpj: str, agora: str) -> None:
    """Atualiza ``empresa.ultima_consulta``. Não toca em ``primeira_consulta``."""
    con.execute(
        text("UPDATE empresa SET ultima_consulta = :agora WHERE cnpj = :cnpj"),
        {"agora": agora, "cnpj": cnpj},
    )


def registrar_falha(
    con: Connection,
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
        text(
            "INSERT INTO falha_coleta (cnpj, ocorrido_em, fonte, motivo) "
            "VALUES (:cnpj, :ocorrido_em, :fonte, :motivo)"
        ),
        {"cnpj": cnpj, "ocorrido_em": ocorrido_em, "fonte": fonte, "motivo": motivo},
    )


def ultima_falha(con: Connection, cnpj: str) -> dict[str, Any] | None:
    """A falha de coleta mais recente da empresa, ou ``None`` se nunca falhou."""
    linha = (
        con.execute(
            text(
                "SELECT * FROM falha_coleta WHERE cnpj = :cnpj "
                "ORDER BY ocorrido_em DESC, id DESC LIMIT 1"
            ),
            {"cnpj": cnpj},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def marcar_acompanhamento(con: Connection, cnpj: str, *, acompanhando: bool) -> None:
    """Inclui a empresa na recoleta diária, ou a tira de lá."""
    con.execute(
        text("UPDATE empresa SET acompanhando = :acompanhando WHERE cnpj = :cnpj"),
        # A coluna é INTEGER 0/1 nos dois bancos; bool do Python viraria
        # BOOLEAN no PostgreSQL, que não converte sozinho para INTEGER.
        {"acompanhando": int(acompanhando), "cnpj": cnpj},
    )


def cnpjs_acompanhados(con: Connection) -> list[str]:
    """CNPJs marcados para a recoleta diária, em ordem."""
    return list(
        con.execute(text("SELECT cnpj FROM empresa WHERE acompanhando = 1 ORDER BY cnpj")).scalars()
    )


def empresa_por_cnpj(con: Connection, cnpj: str) -> dict[str, Any] | None:
    """Devolve a empresa como ``dict`` ou ``None`` se não existir."""
    linha = (
        con.execute(text("SELECT * FROM empresa WHERE cnpj = :cnpj"), {"cnpj": cnpj})
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def registrar_pergunta(
    con: Connection,
    *,
    feita_em: str,
    texto: str,
    modelo: str,
    desfecho: str,
    chamadas: int,
    tokens_entrada: int,
    tokens_saida: int,
) -> None:
    """Registra uma pergunta feita ao assistente e quanto ela gastou."""
    con.execute(
        text(
            "INSERT INTO pergunta "
            "(feita_em, texto, modelo, desfecho, chamadas, tokens_entrada, tokens_saida) "
            "VALUES (:feita_em, :texto, :modelo, :desfecho, :chamadas, "
            ":tokens_entrada, :tokens_saida)"
        ),
        {
            "feita_em": feita_em,
            "texto": texto,
            "modelo": modelo,
            "desfecho": desfecho,
            "chamadas": chamadas,
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
        },
    )


def perguntas_desde(con: Connection, momento: str) -> int:
    """Quantas perguntas foram feitas a partir de ``momento``, inclusive."""
    return con.execute(
        text("SELECT COUNT(*) FROM pergunta WHERE feita_em >= :momento"), {"momento": momento}
    ).scalar_one()
