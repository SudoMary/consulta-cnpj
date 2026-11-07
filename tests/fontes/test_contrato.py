"""Contrato que toda fonte cumpre: é dele que o `cliente.py` vai depender.

Cada teste roda uma vez por adapter. `buscar` usa `httpx.MockTransport`: o
cliente HTTP é de verdade e só a rede é falsa. Nenhum teste aqui precisa de
internet.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import ModuleType
from typing import Any

import httpx
import pytest

from src.db import conectar
from src.fontes import brasilapi, minhareceita
from src.repo import inserir_empresa_se_nao_existe, inserir_observacao, observacoes_por_cnpj

CNPJ = "11222333000181"
BASE_URL = "https://fonte.exemplo/api"
QUANDO = "2026-11-06 12:00:00"
CAMINHOS = {
    "brasilapi": f"/cnpj/v1/{CNPJ}",
    "minhareceita": f"/{CNPJ}",
}

Responder = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(params=[brasilapi, minhareceita], ids=lambda modulo: modulo.NOME)
def fonte(request: pytest.FixtureRequest) -> ModuleType:
    return request.param


@pytest.fixture
def exemplo(fonte: ModuleType, request: pytest.FixtureRequest) -> dict[str, Any]:
    """Resposta real salva da fonte em teste."""
    return request.getfixturevalue(f"exemplo_{fonte.NOME}")


def _buscar(
    fonte: ModuleType, responder: Responder, base_url: str = BASE_URL, timeout: float = 8
) -> httpx.Response:
    """Chama `fonte.buscar` com `responder` no lugar da rede."""
    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        return fonte.buscar(CNPJ, cliente=cliente, base_url=base_url, timeout=timeout)


def _capturar(pedidos: list[httpx.Request]) -> Responder:
    """Devolve um `responder` que guarda em `pedidos` cada pedido recebido."""

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(200, json={})

    return responder


class TestBuscar:
    def test_faz_um_get_na_url_do_cnpj(self, fonte: ModuleType) -> None:
        # Arrange
        pedidos: list[httpx.Request] = []

        # Act
        _buscar(fonte, _capturar(pedidos))

        # Assert
        assert len(pedidos) == 1
        assert pedidos[0].method == "GET"
        assert str(pedidos[0].url) == f"{BASE_URL}{CAMINHOS[fonte.NOME]}"

    def test_barra_no_fim_da_base_url_nao_duplica(self, fonte: ModuleType) -> None:
        pedidos: list[httpx.Request] = []

        _buscar(fonte, _capturar(pedidos), base_url=f"{BASE_URL}/")

        assert str(pedidos[0].url) == f"{BASE_URL}{CAMINHOS[fonte.NOME]}"

    def test_aplica_o_timeout_recebido(self, fonte: ModuleType) -> None:
        # sem prazo, uma fonte lenta trava o processo inteiro
        pedidos: list[httpx.Request] = []

        _buscar(fonte, _capturar(pedidos), timeout=3)

        assert pedidos[0].extensions["timeout"]["read"] == 3

    @pytest.mark.parametrize("status", [400, 404, 429, 500])
    def test_devolve_erro_http_sem_interpretar(self, fonte: ModuleType, status: int) -> None:
        # 404, 429 e 5xx pedem reações diferentes; quem decide é o cliente.py
        resposta = _buscar(fonte, lambda _pedido: httpx.Response(status, json={"message": "erro"}))

        assert resposta.status_code == status

    def test_erro_de_rede_sobe_para_quem_chamou(self, fonte: ModuleType) -> None:
        def responder(pedido: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("simulado", request=pedido)

        with pytest.raises(httpx.ConnectTimeout):
            _buscar(fonte, responder)

    def test_resposta_pode_ser_normalizada(
        self, fonte: ModuleType, exemplo: dict[str, Any]
    ) -> None:
        resposta = _buscar(fonte, lambda _pedido: httpx.Response(200, json=exemplo))

        assert fonte.normalizar(resposta.json()) == fonte.normalizar(exemplo)


class TestNormalizar:
    def test_as_duas_fontes_normalizam_igual(
        self, exemplo_brasilapi: dict[str, Any], exemplo_minhareceita: dict[str, Any]
    ) -> None:
        # O fallback não pode inventar mudança: se a fonte trocar entre duas
        # coletas do mesmo CNPJ, as observações têm de sair iguais.
        assert brasilapi.normalizar(exemplo_brasilapi) == minhareceita.normalizar(
            exemplo_minhareceita
        )


class TestGravacao:
    def test_saida_do_adapter_grava_e_volta_igual(
        self, fonte: ModuleType, exemplo: dict[str, Any]
    ) -> None:
        # Arrange
        dados = fonte.normalizar(exemplo)
        con = conectar(":memory:")

        try:
            # Act: `NOME` precisa passar no CHECK de `observacao.fonte`
            inserir_empresa_se_nao_existe(con, CNPJ, QUANDO)
            inserir_observacao(
                con,
                cnpj=CNPJ,
                dados=dados,
                fonte=fonte.NOME,
                coletado_em=QUANDO,
                bruto_json=json.dumps(exemplo),
            )
            [observacao] = observacoes_por_cnpj(con, CNPJ)
        finally:
            con.close()

        # Assert: toda chave do adapter existe como coluna, com o mesmo valor
        assert observacao["fonte"] == fonte.NOME
        assert {campo: observacao[campo] for campo in dados} == dados
