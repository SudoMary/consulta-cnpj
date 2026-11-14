"""Cliente mínimo da API do OpenRouter, no formato de chat da OpenAI.

O OpenRouter dá acesso a modelos grátis (os terminados em ``:free``), com cota
de 50 requisições por dia no plano grátis. O assistente usa este cliente quando
não há chave da Anthropic.

Modelo grátis sobrecarregado no fornecedor (a fila é dividida entre todos os
usuários do plano grátis) é tentado de novo com espera crescente, como as
fontes de CNPJ em `cliente.py`. Esse erro não desconta da cota; o fim da cota,
sim, e para na hora.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

URL = "https://openrouter.ai/api/v1/chat/completions"
# Modelo pensando e chamando ferramentas leva dezenas de segundos.
TIMEOUT_SEGUNDOS = 120.0
# Espera, em segundos, antes de cada nova tentativa quando o modelo está sobrecarregado.
ESPERAS_SOBRECARGA = (15.0, 30.0, 60.0)

Enviar = Callable[[dict[str, Any]], dict[str, Any]]


class ErroOpenRouter(Exception):
    """A API falhou; a mensagem está pronta para mostrar ao usuário."""


class _Sobrecarregado(Exception):
    """O fornecedor do modelo grátis está cheio; vale tentar de novo."""


def enviar_openrouter(
    chave: str, *, http: httpx.Client, dormir: Callable[[float], None] = time.sleep
) -> Enviar:
    """Função que manda um pedido ao OpenRouter e devolve a resposta como dict."""

    def enviar(pedido: dict[str, Any]) -> dict[str, Any]:
        for tentativa, espera in enumerate((*ESPERAS_SOBRECARGA, None), start=1):
            try:
                return _enviar_uma_vez(pedido, chave, http)
            except _Sobrecarregado as erro:
                if espera is None:
                    raise ErroOpenRouter(
                        f"O modelo {pedido.get('model')} está sobrecarregado no fornecedor "
                        f"depois de {tentativa} tentativas. Tente mais tarde."
                    ) from erro
                dormir(espera)
        raise AssertionError("inalcançável")

    return enviar


def _enviar_uma_vez(pedido: dict[str, Any], chave: str, http: httpx.Client) -> dict[str, Any]:
    try:
        resposta = http.post(
            URL,
            json=pedido,
            headers={"Authorization": f"Bearer {chave}", "X-Title": "consulta-cnpj"},
            timeout=TIMEOUT_SEGUNDOS,
        )
    except httpx.HTTPError as erro:
        raise ErroOpenRouter("Sem conexão com o OpenRouter.") from erro
    if resposta.status_code == 429:
        if "upstream" in resposta.text:
            raise _Sobrecarregado(resposta.text)
        raise ErroOpenRouter(
            "O OpenRouter recusou por limite de uso: o plano grátis dá 50 requisições por dia."
        )
    if resposta.status_code >= 400:
        raise ErroOpenRouter(f"O OpenRouter respondeu HTTP {resposta.status_code}.")
    corpo = resposta.json()
    if "error" in corpo:
        mensagem = corpo["error"].get("message", "erro sem mensagem")
        raise ErroOpenRouter(f"O OpenRouter devolveu um erro: {mensagem}")
    return corpo
