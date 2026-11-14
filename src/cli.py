"""Linha de comando: `consultar <cnpj>`, `acompanhar <cnpj>` e `perguntar "<pergunta>"`.

Liga as peças e formata o que o serviço devolve. Quem calcula devolve dado;
quem imprime só formata: nenhuma regra de negócio mora aqui.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from functools import partial
from typing import Any

import anthropic
import httpx

from .assistente import MENSAGEM_SEM_CHAVE, AssistenteIndisponivel, criar_cliente, perguntar
from .cliente import CnpjNaoEncontrado, TodasAsFontesFalharam, consultar_externo
from .config import Settings
from .db import criar_motor
from .formatacao import (
    MENSAGEM_NAO_ENCONTRADO,
    MENSAGEM_SEM_FONTES,
    campos_da_ficha,
    descrever_origem,
)
from .servico import Consulta, RegraDeNegocio, acompanhar, consultar, mudancas
from .validacao import formata_cnpj


def main(
    argumentos: list[str] | None = None,
    *,
    transporte: httpx.BaseTransport | None = None,
    cliente_ia: anthropic.Anthropic | None = None,
) -> int:
    """Executa o comando e devolve o código de saída do processo.

    `transporte` e `cliente_ia` existem para os testes trocarem a rede e a API
    do Claude por falsas. O OpenRouter passa pelo mesmo `transporte`.
    """
    args = _interpretar(argumentos)
    config = Settings()
    motor = criar_motor(config.url_banco)
    try:
        with httpx.Client(transport=transporte) as http:
            if args.comando == "perguntar":
                escolhido = (
                    (cliente_ia, config.assistente_modelo)
                    if cliente_ia is not None
                    else criar_cliente(config, http=http)
                )
                if escolhido is None:
                    return _falhar(MENSAGEM_SEM_CHAVE)
                cliente, modelo = escolhido
                resposta = perguntar(
                    args.pergunta,
                    motor=motor,
                    cliente=cliente,
                    modelo=modelo,
                    limite_diario=config.assistente_limite_diario,
                )
                print(resposta.texto)
                return 0
            coletar = partial(consultar_externo, http=http, config=config)
            if args.comando == "acompanhar":
                consulta = acompanhar(
                    args.cnpj, motor=motor, coletar=coletar, ttl_horas=config.cache_ttl_horas
                )
                print(formatar_acompanhamento(consulta))
                return 0
            consulta = consultar(
                args.cnpj,
                motor=motor,
                coletar=coletar,
                ttl_horas=config.cache_ttl_horas,
                forcar=args.forcar,
            )
        print(formatar_ficha(consulta))
        print()
        print(formatar_mudancas(mudancas(motor, consulta.observacao["cnpj"])))
    except RegraDeNegocio as erro:
        return _falhar(str(erro))
    except CnpjNaoEncontrado:
        return _falhar(MENSAGEM_NAO_ENCONTRADO)
    except TodasAsFontesFalharam:
        return _falhar(MENSAGEM_SEM_FONTES)
    except AssistenteIndisponivel as erro:
        return _falhar(str(erro))
    finally:
        motor.dispose()
    return 0


def formatar_ficha(consulta: Consulta) -> str:
    """Monta a ficha da empresa, com a origem do dado na última linha."""
    campos = [*campos_da_ficha(consulta.observacao), ("Origem", descrever_origem(consulta))]
    return "\n".join(f"{rotulo + ':':<16}{valor}" for rotulo, valor in campos)


def formatar_acompanhamento(consulta: Consulta) -> str:
    """Confirma que a empresa entrou na recoleta diária."""
    observacao = consulta.observacao
    return (
        f"Acompanhando {formata_cnpj(observacao['cnpj'])} ({observacao['razao_social']}). "
        "A coleta diária passa a incluí-la."
    )


def formatar_mudancas(lista: Iterable[dict[str, Any]]) -> str:
    """Monta a linha do tempo das mudanças. `quando` vem em UTC, como no banco."""
    linhas = [
        f"  {mudanca['quando']}  {mudanca['campo']}: {mudanca['de']} -> {mudanca['para']}"
        for mudanca in lista
    ]
    if not linhas:
        return "Nenhuma mudança detectada."
    return "\n".join(["Mudanças detectadas (horário UTC):", *linhas])


def _falhar(mensagem: str) -> int:
    print(mensagem, file=sys.stderr)
    return 1


def _interpretar(argumentos: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli", description="Consulta de CNPJ com histórico."
    )
    comandos = parser.add_subparsers(dest="comando", required=True)
    comando = comandos.add_parser("consultar", help="mostra a ficha da empresa e o que mudou")
    comando.add_argument("cnpj", help="CNPJ, com ou sem máscara")
    comando.add_argument("--forcar", action="store_true", help="ignora o cache e chama as fontes")
    comando = comandos.add_parser("acompanhar", help="inclui a empresa na recoleta diária")
    comando.add_argument("cnpj", help="CNPJ, com ou sem máscara")
    comando = comandos.add_parser(
        "perguntar", help="pergunta ao assistente sobre as empresas já consultadas"
    )
    comando.add_argument("pergunta", help='entre aspas: "quais empresas mudaram este mês?"')
    return parser.parse_args(argumentos)


if __name__ == "__main__":
    raise SystemExit(main())
