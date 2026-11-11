"""Regras do negócio: cache, gravação append-only e detecção de mudança.

Recebe de fora o banco (`motor`), quem coleta (`coletar`) e o relógio (`agora`),
então as regras testam sem rede e sem esperar o tempo passar. É aqui que vive a
transação: o `repo.py` não faz commit, e cada conjunto de gravações entra
inteiro ou não entra.

Datas são gravadas em UTC, no formato 'YYYY-MM-DD HH:MM:SS' do schema.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import Connection, Engine

from . import repo
from .cliente import Coleta, ErroDeFonte, TodasAsFontesFalharam
from .validacao import cnpj_valido, so_digitos

# Decisão de negócio: estes campos importam, os outros não. Comparar tudo
# acusaria mudança em detalhe irrelevante, como a ordem dos sócios.
CAMPOS_VIGIADOS = (
    "razao_social",
    "situacao",
    "porte",
    "cnae_codigo",
    "municipio",
    "uf",
    "qtd_socios",
)

ORIGEM_CACHE = "cache"
ORIGEM_CACHE_VENCIDO = "cache vencido"

# Sem login na v1, qualquer visitante pode acompanhar uma empresa. O limite
# protege a cota das APIs públicas gratuitas que a coleta diária usa.
LIMITE_ACOMPANHADAS = 20

# No painel, mudança percebida há até tantos dias conta como novidade.
DIAS_DE_MUDANCA_RECENTE = 7

_FORMATO_DATA = "%Y-%m-%d %H:%M:%S"
_PRIORIDADE_NO_PAINEL = {"mudanca": 0, "falha": 1, "ok": 2}


class RegraDeNegocio(Exception):
    """Erro previsto, com mensagem pronta para mostrar ao usuário."""


@dataclass(frozen=True)
class Consulta:
    """Resultado de uma consulta.

    `origem` é o nome da fonte que respondeu agora, `ORIGEM_CACHE` ou
    `ORIGEM_CACHE_VENCIDO`, quando as fontes falharam e sobrou o dado antigo.
    """

    observacao: dict[str, Any]
    origem: str
    idade_horas: float


@dataclass(frozen=True)
class Historico:
    """O que se sabe da empresa ao longo do tempo, para a linha do tempo."""

    mudancas: list[dict[str, Any]]
    primeira_consulta: str | None
    acompanhando: bool


@dataclass(frozen=True)
class ItemDoPainel:
    """Uma empresa acompanhada, com o que precisa de atenção nela.

    `estado` é "mudanca" (mudou há pouco), "falha" (a tentativa mais recente
    de coleta falhou) ou "ok".
    """

    cnpj: str
    observacao: dict[str, Any] | None
    ultima_mudanca: dict[str, Any] | None
    primeira_consulta: str
    estado: str


def validar_cnpj(cnpj_digitado: str | None) -> str:
    """Devolve só os dígitos do CNPJ, ou levanta `RegraDeNegocio` se ele não fechar."""
    if not cnpj_valido(cnpj_digitado):
        raise RegraDeNegocio("CNPJ inválido: confira os 14 dígitos digitados.")
    return so_digitos(cnpj_digitado)  # type: ignore[arg-type]


def consultar(
    cnpj_digitado: str,
    *,
    motor: Engine,
    coletar: Callable[[str], Coleta],
    ttl_horas: int,
    forcar: bool = False,
    agora: datetime | None = None,
) -> Consulta:
    """Devolve os dados do CNPJ, do cache quando possível.

    Levanta `RegraDeNegocio` para CNPJ inválido, antes de qualquer chamada
    externa. Deixa subir `CnpjNaoEncontrado`, e `TodasAsFontesFalharam` quando
    não há observação antiga para entregar no lugar.
    """
    cnpj = validar_cnpj(cnpj_digitado)
    agora = agora or datetime.now(UTC)
    with motor.connect() as con:
        recente = repo.observacao_mais_nova(con, cnpj)

    if recente is not None and not forcar:
        idade = _idade_horas(recente, agora)
        if idade < ttl_horas:
            return Consulta(recente, ORIGEM_CACHE, idade)

    try:
        coleta = coletar(cnpj)
    except TodasAsFontesFalharam as falha:
        with motor.begin() as con:
            _registrar_falhas(con, cnpj, falha.erros, agora)
        if recente is None:
            raise
        return Consulta(recente, ORIGEM_CACHE_VENCIDO, _idade_horas(recente, agora))

    with motor.begin() as con:
        _registrar_falhas(con, cnpj, coleta.erros, agora)
        _gravar_observacao(con, cnpj, coleta, agora)
        nova = repo.observacao_mais_nova(con, cnpj)

    return Consulta(nova, coleta.fonte, 0)  # type: ignore[arg-type]


def acompanhar(
    cnpj_digitado: str,
    *,
    motor: Engine,
    coletar: Callable[[str], Coleta],
    ttl_horas: int,
    agora: datetime | None = None,
) -> Consulta:
    """Inclui a empresa na recoleta diária e devolve a consulta feita antes.

    Consulta primeiro para só acompanhar empresa que existe: CNPJ inválido ou
    não encontrado sobe como na consulta comum, sem marcar nada. Passado o
    limite de empresas acompanhadas, levanta `RegraDeNegocio` antes de consultar.
    """
    cnpj = validar_cnpj(cnpj_digitado)
    with motor.connect() as con:
        acompanhadas = repo.cnpjs_acompanhados(con)
    if cnpj not in acompanhadas and len(acompanhadas) >= LIMITE_ACOMPANHADAS:
        raise RegraDeNegocio(
            f"O limite de {LIMITE_ACOMPANHADAS} empresas acompanhadas foi atingido. "
            "A coleta diária usa APIs públicas gratuitas e não deve sobrecarregá-las."
        )

    consulta = consultar(cnpj, motor=motor, coletar=coletar, ttl_horas=ttl_horas, agora=agora)
    with motor.begin() as con:
        repo.marcar_acompanhamento(con, consulta.observacao["cnpj"], acompanhando=True)
    return consulta


def mudancas(motor: Engine, cnpj: str) -> list[dict[str, Any]]:
    """Compara observações consecutivas e lista o que mudou nos campos vigiados."""
    with motor.connect() as con:
        observacoes = repo.observacoes_por_cnpj(con, cnpj)
    return _comparar(observacoes)


def historico(motor: Engine, cnpj: str) -> Historico:
    """Mudanças, data da primeira consulta e se a empresa está na coleta diária."""
    with motor.connect() as con:
        observacoes = repo.observacoes_por_cnpj(con, cnpj)
        empresa = repo.empresa_por_cnpj(con, cnpj)
    return Historico(
        mudancas=_comparar(observacoes),
        primeira_consulta=empresa["primeira_consulta"] if empresa else None,
        acompanhando=bool(empresa and empresa["acompanhando"]),
    )


def painel(motor: Engine, *, agora: datetime | None = None) -> list[ItemDoPainel]:
    """Empresas acompanhadas, com mudanças recentes e falhas primeiro."""
    agora = agora or datetime.now(UTC)
    itens: list[ItemDoPainel] = []
    with motor.connect() as con:
        for cnpj in repo.cnpjs_acompanhados(con):
            observacoes = repo.observacoes_por_cnpj(con, cnpj)
            falha = repo.ultima_falha(con, cnpj)
            empresa = repo.empresa_por_cnpj(con, cnpj)
            lista = _comparar(observacoes)
            ultima_mudanca = lista[-1] if lista else None
            recente = observacoes[-1] if observacoes else None
            itens.append(
                ItemDoPainel(
                    cnpj=cnpj,
                    observacao=recente,
                    ultima_mudanca=ultima_mudanca,
                    primeira_consulta=empresa["primeira_consulta"],  # type: ignore[index]
                    estado=_estado_no_painel(ultima_mudanca, recente, falha, agora),
                )
            )
    return sorted(
        itens,
        key=lambda item: (
            _PRIORIDADE_NO_PAINEL[item.estado],
            (item.observacao or {}).get("razao_social") or "",
        ),
    )


def _estado_no_painel(
    ultima_mudanca: dict[str, Any] | None,
    recente: dict[str, Any] | None,
    falha: dict[str, Any] | None,
    agora: datetime,
) -> str:
    if ultima_mudanca and _horas_desde(ultima_mudanca["quando"], agora) <= (
        DIAS_DE_MUDANCA_RECENTE * 24
    ):
        return "mudanca"
    # Falha registrada no mesmo instante da observação é da fonte primária
    # numa coleta que a reserva salvou: a coleta deu certo.
    if falha and (recente is None or falha["ocorrido_em"] > recente["coletado_em"]):
        return "falha"
    return "ok"


def _comparar(observacoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lista: list[dict[str, Any]] = []
    for antes, depois in pairwise(observacoes):
        for campo in CAMPOS_VIGIADOS:
            if antes[campo] != depois[campo]:
                lista.append(
                    {
                        "campo": campo,
                        "de": antes[campo],
                        "para": depois[campo],
                        "quando": depois["coletado_em"],
                    }
                )
    return lista


def _gravar_observacao(con: Connection, cnpj: str, coleta: Coleta, agora: datetime) -> None:
    carimbo = _carimbo(agora)
    repo.inserir_empresa_se_nao_existe(con, cnpj, carimbo)
    repo.inserir_observacao(
        con,
        cnpj=cnpj,
        dados=coleta.dados,
        fonte=coleta.fonte,
        coletado_em=carimbo,
        bruto_json=coleta.bruto_json,
    )
    repo.atualizar_ultima_consulta(con, cnpj, carimbo)


def _registrar_falhas(
    con: Connection, cnpj: str, erros: Iterable[ErroDeFonte], agora: datetime
) -> None:
    carimbo = _carimbo(agora)
    for erro in erros:
        repo.registrar_falha(
            con, cnpj=cnpj, fonte=erro.fonte, motivo=erro.motivo, ocorrido_em=carimbo
        )


def _carimbo(instante: datetime) -> str:
    return instante.astimezone(UTC).strftime(_FORMATO_DATA)


def _idade_horas(observacao: dict[str, Any], agora: datetime) -> float:
    return _horas_desde(observacao["coletado_em"], agora)


def _horas_desde(momento: str, agora: datetime) -> float:
    instante = datetime.strptime(momento, _FORMATO_DATA).replace(tzinfo=UTC)
    return (agora - instante).total_seconds() / 3600
