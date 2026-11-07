"""Cliente externo: fallback entre fontes, retry com espera crescente e timeout.

É a única peça que interpreta as respostas das fontes:

- 200 com dados válidos: sucesso.
- 404: o CNPJ não existe. É resposta, não falha: não adianta repetir nem
  perguntar à reserva.
- 429, 5xx, timeout e erro de rede: repete com espera crescente; se não
  resolver, passa para a próxima fonte.
- Qualquer outra resposta, incluindo 200 fora do formato: falha sem repetição,
  porque repetir não muda a resposta. O corpo nunca chega ao `normalizar`, ou
  um erro viraria uma observação cheia de nulos no histórico.

Não grava nada. Devolve o que coletou e os erros que encontrou, mesmo quando
uma fonte resolveu depois de outra falhar, e o `servico.py` decide o que guardar.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any, NamedTuple

import httpx

from .config import Settings
from .fontes import brasilapi, minhareceita

TENTATIVAS_POR_FONTE = 3


class ErroDeFonte(NamedTuple):
    """Uma tentativa que falhou, no formato de `falha_coleta`."""

    fonte: str
    motivo: str


class CnpjNaoEncontrado(Exception):
    """Uma fonte respondeu 404: o CNPJ é válido, mas não está na base."""


class TodasAsFontesFalharam(Exception):
    """Nenhuma fonte devolveu dados; `erros` traz cada tentativa que falhou."""

    def __init__(self, erros: list[ErroDeFonte]) -> None:
        super().__init__("Todas as fontes falharam.")
        self.erros = erros


@dataclass(frozen=True)
class Coleta:
    """Dados obtidos de uma fonte e os erros encontrados até consegui-los."""

    dados: dict[str, Any]
    fonte: str
    bruto_json: str
    erros: tuple[ErroDeFonte, ...] = ()


class _Falha(NamedTuple):
    motivo: str
    vale_repetir: bool


def consultar_externo(
    cnpj: str,
    *,
    http: httpx.Client,
    config: Settings,
    esperar: Callable[[float], None] = time.sleep,
) -> Coleta:
    """Busca o CNPJ nas fontes, em ordem de prioridade.

    Levanta `CnpjNaoEncontrado` no primeiro 404 e `TodasAsFontesFalharam` se
    nenhuma fonte devolver dados. `esperar` é injetado para testar sem dormir.
    """
    # A ordem é a prioridade.
    fontes = (
        (brasilapi, config.brasilapi_base_url),
        (minhareceita, config.minhareceita_base_url),
    )
    erros: list[ErroDeFonte] = []

    for fonte, base_url in fontes:
        for tentativa in range(1, TENTATIVAS_POR_FONTE + 1):
            resultado = _tentar(fonte, cnpj, http, base_url, config.http_timeout_segundos)
            if isinstance(resultado, Coleta):
                return replace(resultado, erros=tuple(erros))

            erros.append(ErroDeFonte(fonte.NOME, resultado.motivo))
            if not resultado.vale_repetir:
                break
            # Depois da última tentativa, a próxima chamada é em outra fonte:
            # não há o que esperar.
            if tentativa < TENTATIVAS_POR_FONTE:
                esperar(2**tentativa)

    raise TodasAsFontesFalharam(erros)


def _tentar(
    fonte: ModuleType, cnpj: str, http: httpx.Client, base_url: str, timeout: float
) -> Coleta | _Falha:
    """Faz uma tentativa em uma fonte e classifica o resultado."""
    try:
        resposta = fonte.buscar(cnpj, cliente=http, base_url=base_url, timeout=timeout)
    except httpx.TimeoutException:
        return _Falha("timeout", vale_repetir=True)
    except httpx.HTTPError as erro:
        return _Falha(f"erro de rede: {type(erro).__name__}", vale_repetir=True)

    status = resposta.status_code
    if status == 404:
        raise CnpjNaoEncontrado(cnpj)
    if status != 200:
        return _Falha(f"HTTP {status}", vale_repetir=status == 429 or status >= 500)

    dados = _ler_dados(fonte, resposta)
    if dados is None:
        return _Falha("resposta fora do formato esperado", vale_repetir=False)
    return Coleta(dados=dados, fonte=fonte.NOME, bruto_json=resposta.text)


def _ler_dados(fonte: ModuleType, resposta: httpx.Response) -> dict[str, Any] | None:
    """Normaliza o corpo da resposta, ou devolve ``None`` se ele não servir."""
    try:
        corpo = resposta.json()
        dados = fonte.normalizar(corpo) if isinstance(corpo, dict) else None
    except (TypeError, ValueError):
        return None
    # Empresa sem razão social não existe: é sinal de resposta quebrada.
    return dados if dados and dados["razao_social"] else None
