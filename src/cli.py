"""Linha de comando: `python -m src.cli consultar <cnpj>` e `acompanhar <cnpj>`.

Liga as peças e formata o que o serviço devolve. Quem calcula devolve dado;
quem imprime só formata: nenhuma regra de negócio mora aqui.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from functools import partial
from typing import Any

import httpx

from .cliente import CnpjNaoEncontrado, TodasAsFontesFalharam, consultar_externo
from .config import Settings
from .db import criar_motor
from .servico import (
    ORIGEM_CACHE,
    ORIGEM_CACHE_VENCIDO,
    Consulta,
    RegraDeNegocio,
    acompanhar,
    consultar,
    mudancas,
)
from .validacao import formata_cnpj

_NAO_INFORMADO = "não informado"


def main(
    argumentos: list[str] | None = None, *, transporte: httpx.BaseTransport | None = None
) -> int:
    """Executa o comando e devolve o código de saída do processo.

    `transporte` existe para os testes trocarem a rede por uma falsa.
    """
    args = _interpretar(argumentos)
    config = Settings()
    motor = criar_motor(config.url_banco)
    try:
        with httpx.Client(transport=transporte) as http:
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
        return _falhar("CNPJ não encontrado na base da Receita.")
    except TodasAsFontesFalharam:
        return _falhar(
            "As fontes estão fora do ar e não há consulta anterior deste CNPJ. "
            "Tente de novo mais tarde."
        )
    finally:
        motor.dispose()
    return 0


def formatar_ficha(consulta: Consulta) -> str:
    """Monta a ficha da empresa, com a origem do dado na última linha."""
    observacao = consulta.observacao
    campos = (
        ("CNPJ", formata_cnpj(observacao["cnpj"])),
        ("Razão social", observacao["razao_social"]),
        ("Nome fantasia", observacao["nome_fantasia"]),
        ("Situação", observacao["situacao"]),
        ("Desde", observacao["data_situacao"]),
        ("Porte", observacao["porte"]),
        ("CNAE", observacao["cnae_codigo"]),
        ("Atividade", observacao["cnae_descricao"]),
        ("Município", observacao["municipio"]),
        ("UF", observacao["uf"]),
        ("Capital social", formatar_capital(observacao["capital_centavos"])),
        ("Sócios", observacao["qtd_socios"]),
        ("Origem", descrever_origem(consulta)),
    )
    return "\n".join(f"{rotulo + ':':<16}{_valor(valor)}" for rotulo, valor in campos)


def formatar_acompanhamento(consulta: Consulta) -> str:
    """Confirma que a empresa entrou na recoleta diária."""
    observacao = consulta.observacao
    return (
        f"Acompanhando {formata_cnpj(observacao['cnpj'])} ({observacao['razao_social']}). "
        "A coleta diária passa a incluí-la."
    )


def formatar_capital(centavos: int | None) -> str:
    """Formata centavos como reais, sem passar por float."""
    if centavos is None:
        return _NAO_INFORMADO
    reais, resto = divmod(centavos, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{resto:02d}"


def formatar_mudancas(lista: Iterable[dict[str, Any]]) -> str:
    """Monta a linha do tempo das mudanças. `quando` vem em UTC, como no banco."""
    linhas = [
        f"  {mudanca['quando']}  {mudanca['campo']}: {mudanca['de']} -> {mudanca['para']}"
        for mudanca in lista
    ]
    if not linhas:
        return "Nenhuma mudança detectada."
    return "\n".join(["Mudanças detectadas (horário UTC):", *linhas])


def descrever_origem(consulta: Consulta) -> str:
    """Diz de onde veio o dado, em frase para o usuário."""
    idade = _idade_por_extenso(consulta.idade_horas)
    if consulta.origem == ORIGEM_CACHE:
        return f"do cache, há {idade}"
    if consulta.origem == ORIGEM_CACHE_VENCIDO:
        return f"consultado há {idade}, as fontes estão fora do ar agora"
    return f"consultado agora em {consulta.origem}"


def _idade_por_extenso(horas: float) -> str:
    if horas < 1:
        return "menos de 1 hora"
    if horas < 2:
        return "1 hora"
    if horas < 48:
        return f"{int(horas)} horas"
    return f"{int(horas // 24)} dias"


def _valor(valor: Any) -> Any:
    return _NAO_INFORMADO if valor is None else valor


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
    return parser.parse_args(argumentos)


if __name__ == "__main__":
    raise SystemExit(main())
