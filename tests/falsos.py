"""Peças falsas compartilhadas pelos testes do serviço, do coletor e do assistente."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any

from src.cliente import Coleta, ErroDeFonte


class ColetaFalsa:
    """Faz o papel de `consultar_externo`: conta as chamadas e segue um roteiro.

    Cada passo é uma `Coleta` devolvida ou uma exceção levantada. Uma chamada
    além do roteiro estoura `IndexError` e reprova o teste.
    """

    def __init__(self, *passos: Coleta | Exception) -> None:
        self.passos = list(passos)
        self.cnpjs: list[str] = []

    @property
    def chamadas(self) -> int:
        return len(self.cnpjs)

    def __call__(self, cnpj: str) -> Coleta:
        self.cnpjs.append(cnpj)
        passo = self.passos.pop(0)
        if isinstance(passo, Exception):
            raise passo
        return passo


def coleta(
    situacao: str = "ATIVA",
    *,
    fonte: str = "brasilapi",
    erros: tuple[ErroDeFonte, ...] = (),
) -> Coleta:
    """Uma coleta bem-sucedida, com o mínimo que o serviço grava."""
    dados = {"razao_social": "ACME LTDA", "situacao": situacao}
    return Coleta(dados=dados, fonte=fonte, bruto_json='{"bruto": true}', erros=erros)


class ClienteIAFalso:
    """Faz o papel do cliente da API do Claude: segue um roteiro e guarda os pedidos.

    Cada passo é uma resposta (ver `resposta_texto` e `resposta_ferramentas`) ou
    uma exceção levantada. Uma chamada além do roteiro estoura `IndexError` e
    reprova o teste.
    """

    def __init__(self, *passos: Any) -> None:
        self.passos = list(passos)
        self.pedidos: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._criar))

    @property
    def chamadas(self) -> int:
        return len(self.pedidos)

    def _criar(self, **parametros: Any) -> Any:
        # Copia a lista: o assistente continua acrescentando mensagens nela.
        self.pedidos.append({**parametros, "messages": list(parametros["messages"])})
        passo = self.passos.pop(0)
        if isinstance(passo, Exception):
            raise passo
        return passo


def _uso(entrada: int = 100, saida: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=entrada,
        output_tokens=saida,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def resposta_texto(texto: str, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    """Resposta final do modelo, só com texto."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=texto)],
        stop_reason=stop_reason,
        usage=_uso(),
    )


def resposta_ferramentas(*pedidos: tuple[str, dict[str, Any]]) -> SimpleNamespace:
    """O modelo pede uma ou mais ferramentas, cada uma como ``(nome, entrada)``."""
    blocos = [
        SimpleNamespace(type="tool_use", id=f"toolu_{numero}", name=nome, input=entrada)
        for numero, (nome, entrada) in enumerate(pedidos, start=1)
    ]
    return SimpleNamespace(content=blocos, stop_reason="tool_use", usage=_uso())


def resposta_recusa() -> SimpleNamespace:
    """O modelo recusou a pergunta por política de uso."""
    return SimpleNamespace(content=[], stop_reason="refusal", usage=_uso(saida=0))


class OpenRouterFalso:
    """Faz o papel do `enviar` do OpenRouter: segue um roteiro e guarda os pedidos."""

    def __init__(self, *passos: Any) -> None:
        self.passos = list(passos)
        self.pedidos: list[dict[str, Any]] = []

    @property
    def chamadas(self) -> int:
        return len(self.pedidos)

    def __call__(self, pedido: dict[str, Any]) -> dict[str, Any]:
        # Copia fundo: o assistente continua acrescentando mensagens na lista.
        self.pedidos.append(copy.deepcopy(pedido))
        passo = self.passos.pop(0)
        if isinstance(passo, Exception):
            raise passo
        return passo


_USO_OPENROUTER = {"prompt_tokens": 100, "completion_tokens": 20}


def openrouter_texto(texto: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    """Resposta final de um modelo do OpenRouter, só com texto."""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": texto}, "finish_reason": finish_reason}
        ],
        "usage": _USO_OPENROUTER,
    }


def openrouter_ferramentas(*pedidos: tuple[str, dict[str, Any] | str]) -> dict[str, Any]:
    """O modelo pede ferramentas, cada uma como ``(nome, argumentos)``."""
    chamadas = [
        {
            "id": f"call_{numero}",
            "type": "function",
            "function": {
                "name": nome,
                "arguments": argumentos if isinstance(argumentos, str) else json.dumps(argumentos),
            },
        }
        for numero, (nome, argumentos) in enumerate(pedidos, start=1)
    ]
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": None, "tool_calls": chamadas},
                "finish_reason": "tool_calls",
            }
        ],
        "usage": _USO_OPENROUTER,
    }
