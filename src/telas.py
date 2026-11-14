"""O que cada página da tela web mostra, já pronto para o template.

Decisões de apresentação (o que destacar, em que ordem, com que texto) moram
aqui. Regras de negócio continuam no serviço; os templates só desenham.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .assistente import TAMANHO_MAXIMO_DA_PERGUNTA
from .formatacao import (
    NAO_INFORMADO,
    ROTULOS,
    data_br,
    data_hora_br,
    descrever_origem,
    formatar_capital,
    formatar_cnae,
    gravidade_da_situacao,
    ou_nao_informado,
)
from .servico import (
    LIMITE_ACOMPANHADAS,
    ORIGEM_CACHE,
    ORIGEM_CACHE_VENCIDO,
    Consulta,
    Historico,
    ItemDoPainel,
)
from .validacao import formata_cnpj

# Uma mudança de situação ganha destaque no topo da ficha por este tempo.
DIAS_DE_DESTAQUE = 30

FILTROS_DO_PAINEL = (
    ("todas", "Todas"),
    ("mudanca", "Com mudança"),
    ("falha", "Com falha"),
    ("ok", "Sem novidades"),
)


def pagina_do_painel(itens: list[ItemDoPainel], filtro: str = "todas") -> dict[str, Any]:
    """Resumo, filtros com contagem e a lista filtrada de empresas acompanhadas."""
    if filtro not in dict(FILTROS_DO_PAINEL):
        filtro = "todas"
    contagem = {"todas": len(itens)}
    for estado in ("mudanca", "falha", "ok"):
        contagem[estado] = sum(1 for item in itens if item.estado == estado)
    return {
        "total": len(itens),
        "mudancas": contagem["mudanca"],
        "falhas": contagem["falha"],
        "limite": LIMITE_ACOMPANHADAS,
        "filtros": [
            {
                "valor": valor,
                "rotulo": rotulo,
                "quantidade": contagem[valor],
                "ativo": valor == filtro,
            }
            for valor, rotulo in FILTROS_DO_PAINEL
        ],
        "itens": [
            _item_do_painel(item) for item in itens if filtro == "todas" or item.estado == filtro
        ],
    }


def _item_do_painel(item: ItemDoPainel) -> dict[str, Any]:
    observacao = item.observacao or {}
    conteudo: dict[str, Any] = {
        "cnpj": item.cnpj,
        "cnpj_formatado": formata_cnpj(item.cnpj),
        "razao_social": ou_nao_informado(observacao.get("razao_social")),
        "situacao": ou_nao_informado(observacao.get("situacao")),
        "gravidade": gravidade_da_situacao(observacao.get("situacao")),
        "estado": item.estado,
        "mudanca": None,
        "texto": "",
    }
    if item.estado == "mudanca" and item.ultima_mudanca:
        conteudo["mudanca"] = _evento(item.ultima_mudanca)
    elif item.estado == "falha":
        conteudo["texto"] = (
            "A última coleta falhou: as fontes estavam fora do ar. "
            f"A situação mostrada é de {data_hora_br(observacao['coletado_em'])}."
            if observacao
            else "A última coleta falhou, e ainda não há dado desta empresa."
        )
    elif item.ultima_mudanca:
        dia = data_hora_br(item.ultima_mudanca["quando"])[:10]
        conteudo["texto"] = f"Última mudança percebida em {dia}."
    else:
        dia = data_hora_br(item.primeira_consulta)[:10]
        conteudo["texto"] = f"Sem mudanças desde a primeira consulta, em {dia}."
    return conteudo


def pagina_da_empresa(
    consulta: Consulta, historico: Historico, agora: datetime | None = None
) -> dict[str, Any]:
    """Conteúdo da ficha: cabeçalho, origem do dado, cartão e linha do tempo."""
    agora = agora or datetime.now(UTC)
    observacao = consulta.observacao
    recentes_primeiro = list(reversed(historico.mudancas))
    return {
        "cnpj": observacao["cnpj"],
        "cnpj_formatado": formata_cnpj(observacao["cnpj"]),
        "razao_social": ou_nao_informado(observacao["razao_social"]),
        "situacao": ou_nao_informado(observacao["situacao"]),
        "gravidade": gravidade_da_situacao(observacao["situacao"]),
        "situacao_desde": data_br(observacao["data_situacao"])
        if observacao["data_situacao"]
        else None,
        "origem": _origem(consulta),
        "fontes_fora": consulta.origem == ORIGEM_CACHE_VENCIDO,
        "destaque": _destaque(recentes_primeiro, agora),
        "cartao": _cartao(observacao),
        "linha_do_tempo": [_evento(mudanca) for mudanca in recentes_primeiro],
        "primeira_consulta": data_hora_br(historico.primeira_consulta)
        if historico.primeira_consulta
        else None,
        "acompanhando": historico.acompanhando,
    }


def _origem(consulta: Consulta) -> dict[str, str]:
    if consulta.origem == ORIGEM_CACHE:
        tipo = "cache"
    elif consulta.origem == ORIGEM_CACHE_VENCIDO:
        tipo = "fora"
    else:
        tipo = "agora"
    frase = descrever_origem(consulta)
    return {
        "tipo": tipo,
        "texto": frase[0].upper() + frase[1:],
        "quando": data_hora_br(consulta.observacao["coletado_em"]),
    }


def _destaque(recentes_primeiro: list[dict[str, Any]], agora: datetime) -> dict[str, str] | None:
    """A mudança de situação mais recente, se aconteceu há pouco tempo."""
    for mudanca in recentes_primeiro:
        if mudanca["campo"] != "situacao":
            continue
        percebida = datetime.strptime(mudanca["quando"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        if (agora - percebida).days > DIAS_DE_DESTAQUE:
            return None
        return {
            "de": ou_nao_informado(mudanca["de"]),
            "para": ou_nao_informado(mudanca["para"]),
            "quando": data_hora_br(mudanca["quando"]),
        }
    return None


def _evento(mudanca: dict[str, Any]) -> dict[str, Any]:
    return {
        "quando": data_hora_br(mudanca["quando"]),
        "rotulo": ROTULOS[mudanca["campo"]],
        "de": ou_nao_informado(mudanca["de"]),
        "para": ou_nao_informado(mudanca["para"]),
        "grave": mudanca["campo"] == "situacao",
    }


def _cartao(observacao: dict[str, Any]) -> list[dict[str, Any]]:
    atividade = formatar_cnae(observacao["cnae_codigo"])
    if observacao["cnae_descricao"]:
        atividade = f"{atividade} · {observacao['cnae_descricao']}"
    lugar = " / ".join(parte for parte in (observacao["municipio"], observacao["uf"]) if parte)
    return [
        {"rotulo": "Nome fantasia", "valor": ou_nao_informado(observacao["nome_fantasia"])},
        {"rotulo": "Porte", "valor": ou_nao_informado(observacao["porte"])},
        {"rotulo": "Município / UF", "valor": lugar or NAO_INFORMADO},
        {"rotulo": "Atividade principal (CNAE)", "valor": atividade, "largo": True},
        {
            "rotulo": "Capital social",
            "valor": formatar_capital(observacao["capital_centavos"]),
            "mono": True,
        },
        {"rotulo": "Quadro de sócios", "valor": _socios(observacao["qtd_socios"])},
    ]


def _socios(quantidade: int | None) -> str:
    if quantidade is None:
        return NAO_INFORMADO
    if quantidade == 0:
        return "Nenhum sócio informado"
    return "1 sócio" if quantidade == 1 else f"{quantidade} sócios"


EXEMPLOS_DO_ASSISTENTE = (
    "Quais empresas estão sendo acompanhadas?",
    "Alguma empresa acompanhada mudou de situação este mês?",
    "O que mudou nas empresas nos últimos 30 dias?",
)


def pagina_do_assistente(
    *,
    modelo: str | None,
    restantes: int,
    pergunta: str = "",
    resposta: str | None = None,
    erro: str | None = None,
) -> dict[str, Any]:
    """Conteúdo da página do assistente. Sem `modelo`, ele está desligado."""
    if restantes == 1:
        quantas = "Resta 1 pergunta hoje."
    elif restantes:
        quantas = f"Restam {restantes} perguntas hoje."
    else:
        quantas = "As perguntas de hoje acabaram; amanhã tem mais."
    return {
        "ligado": modelo is not None,
        "modelo": modelo,
        "restantes": restantes,
        "quantas": quantas,
        "exemplos": EXEMPLOS_DO_ASSISTENTE,
        "tamanho_maximo": TAMANHO_MAXIMO_DA_PERGUNTA,
        "pergunta": pergunta,
        "resposta": resposta,
        "erro": erro,
    }
