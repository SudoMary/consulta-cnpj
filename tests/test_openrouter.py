"""Testes do cliente HTTP do OpenRouter (src/openrouter.py).

A rede é um `httpx.MockTransport`: nenhum teste chama o OpenRouter de verdade.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.openrouter import ESPERAS_SOBRECARGA, ErroOpenRouter, enviar_openrouter

SOBRECARGA = {"error": {"code": 429, "metadata": {"raw": "temporarily rate-limited upstream"}}}
RESPOSTA = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


def _enviar(
    *respostas: httpx.Response | Exception, esperas: list[float] | None = None
) -> tuple[Callable[[dict[str, Any]], dict[str, Any]], list[httpx.Request]]:
    fila = list(respostas)
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        proxima = fila.pop(0)
        if isinstance(proxima, Exception):
            raise proxima
        return proxima

    http = httpx.Client(transport=httpx.MockTransport(responder))
    dormir = esperas.append if esperas is not None else (lambda _: None)
    return enviar_openrouter("sk-or-teste", http=http, dormir=dormir), pedidos


def test_manda_o_pedido_com_a_chave_e_devolve_a_resposta() -> None:
    enviar, pedidos = _enviar(httpx.Response(200, json=RESPOSTA))

    resposta = enviar({"model": "modelo:free", "messages": []})

    assert resposta == RESPOSTA
    assert pedidos[0].headers["Authorization"] == "Bearer sk-or-teste"
    assert json.loads(pedidos[0].content)["model"] == "modelo:free"


def test_sobrecarga_no_fornecedor_e_tentada_de_novo() -> None:
    esperas: list[float] = []
    enviar, pedidos = _enviar(
        httpx.Response(429, json=SOBRECARGA), httpx.Response(200, json=RESPOSTA), esperas=esperas
    )

    assert enviar({"model": "modelo:free"}) == RESPOSTA
    assert len(pedidos) == 2
    assert esperas == [ESPERAS_SOBRECARGA[0]]


def test_desiste_da_sobrecarga_depois_das_tentativas() -> None:
    respostas = [httpx.Response(429, json=SOBRECARGA)] * (len(ESPERAS_SOBRECARGA) + 1)
    enviar, _ = _enviar(*respostas)

    with pytest.raises(ErroOpenRouter, match="sobrecarregado"):
        enviar({"model": "modelo:free"})


def test_fim_da_cota_para_na_hora() -> None:
    enviar, pedidos = _enviar(httpx.Response(429, json={"error": {"message": "Rate limit"}}))

    with pytest.raises(ErroOpenRouter, match="limite de uso"):
        enviar({"model": "modelo:free"})
    assert len(pedidos) == 1


def test_erro_no_corpo_da_resposta_sobe() -> None:
    enviar, _ = _enviar(httpx.Response(200, json={"error": {"message": "modelo indisponível"}}))

    with pytest.raises(ErroOpenRouter, match="modelo indisponível"):
        enviar({"model": "modelo:free"})


def test_falha_de_rede_vira_mensagem_clara() -> None:
    enviar, _ = _enviar(httpx.ConnectError("sem rede"))

    with pytest.raises(ErroOpenRouter, match="conexão"):
        enviar({"model": "modelo:free"})
