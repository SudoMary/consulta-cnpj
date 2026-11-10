"""Peças falsas compartilhadas pelos testes do serviço e do coletor."""

from __future__ import annotations

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
