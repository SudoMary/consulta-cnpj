"""Testes do adapter da BrasilAPI: `normalizar` e `buscar`.

`normalizar` parte do JSON REAL salvo em `dados/exemplo_brasilapi.json`.
Nenhum nome de campo aqui foi inventado — todos existem no fixture.

`buscar` usa `httpx.MockTransport`: o cliente HTTP é de verdade e só a rede
é falsa. Nenhum teste deste arquivo precisa de internet.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from db import conectar
from fontes.brasilapi import NOME, buscar, normalizar
from repo import inserir_empresa_se_nao_existe, inserir_observacao, observacoes_por_cnpj

CNPJ = "11222333000181"
BASE_URL = "https://brasilapi.exemplo/api"
QUANDO = "2026-11-06 12:00:00"

Responder = Callable[[httpx.Request], httpx.Response]


def _buscar(responder: Responder, base_url: str = BASE_URL, timeout: float = 8) -> httpx.Response:
    """Chama `buscar` com `responder` no lugar da rede."""
    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        return buscar(CNPJ, cliente=cliente, base_url=base_url, timeout=timeout)


class TestNormalizar:
    def test_extrai_razao_social(self, exemplo_brasilapi: dict[str, Any]) -> None:
        # Act
        resultado = normalizar(exemplo_brasilapi)

        # Assert
        assert resultado["razao_social"].startswith("CAIXA ESCOLAR")

    def test_extrai_nome_fantasia(self, exemplo_brasilapi: dict[str, Any]) -> None:
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["nome_fantasia"].startswith("CAIXA ESCOLA")

    def test_situacao_vem_de_descricao_situacao_cadastral(
        self, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        # a API tem DOIS campos com "situacao": `situacao_cadastral` (código 2)
        # e `descricao_situacao_cadastral` (texto ATIVA). O schema quer o texto.
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["situacao"] == "ATIVA"

    def test_data_situacao_vem_de_data_situacao_cadastral(
        self, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["data_situacao"] == "2009-09-02"

    def test_extrai_porte(self, exemplo_brasilapi: dict[str, Any]) -> None:
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["porte"] == "DEMAIS"

    def test_cnae_codigo_vira_string(self, exemplo_brasilapi: dict[str, Any]) -> None:
        # na API `cnae_fiscal` é int (8550301); no schema é TEXT
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["cnae_codigo"] == "8550301"
        assert isinstance(resultado["cnae_codigo"], str)

    def test_cnae_preserva_zero_a_esquerda(self) -> None:
        # CNAE tem 7 dígitos, mas a API entrega int e o zero da frente some:
        # a resposta real da SLC Agrícola traz 161099 para o código 0161-0/99.
        resultado = normalizar({"cnae_fiscal": 161099})
        assert resultado["cnae_codigo"] == "0161099"

    def test_nome_fantasia_vazio_vira_none(self) -> None:
        # empresa sem nome fantasia vem com "" na API; "não informado" é None
        resultado = normalizar({"nome_fantasia": ""})
        assert resultado["nome_fantasia"] is None

    def test_cnae_descricao_vem_de_cnae_fiscal_descricao(
        self, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["cnae_descricao"] == "Administração de caixas escolares"

    def test_extrai_municipio_e_uf(self, exemplo_brasilapi: dict[str, Any]) -> None:
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["municipio"] == "SAO SEBASTIAO DO CAI"
        assert resultado["uf"] == "RS"

    def test_capital_social_zero_vira_zero_centavos(
        self, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["capital_centavos"] == 0
        assert isinstance(resultado["capital_centavos"], int)

    def test_capital_social_com_centavos_e_arredondado(self) -> None:
        # 1.15 * 100 = 114.99999... em float; int() truncaria para 114.
        # round() devolve 115. Este teste trava a decisão.
        json_bruto = {
            "razao_social": "X",
            "capital_social": 1.15,
        }

        resultado = normalizar(json_bruto)

        assert resultado["capital_centavos"] == 115

    def test_qtd_socios_vem_do_tamanho_da_lista(self, exemplo_brasilapi: dict[str, Any]) -> None:
        # `qsa` na API é a lista de sócios
        resultado = normalizar(exemplo_brasilapi)
        assert resultado["qtd_socios"] == 1

    def test_campos_ausentes_viram_none(self) -> None:
        resultado = normalizar({})

        for campo in (
            "razao_social",
            "nome_fantasia",
            "situacao",
            "data_situacao",
            "porte",
            "cnae_codigo",
            "cnae_descricao",
            "municipio",
            "uf",
            "capital_centavos",
            "qtd_socios",
        ):
            assert resultado[campo] is None, campo

    def test_retorna_apenas_os_campos_do_schema(self, exemplo_brasilapi: dict[str, Any]) -> None:
        # o normalizar extrai o que o schema precisa; o resto fica no
        # bruto_json, que o chamador é responsável por salvar.
        resultado = normalizar(exemplo_brasilapi)

        esperado = {
            "razao_social",
            "nome_fantasia",
            "situacao",
            "data_situacao",
            "porte",
            "cnae_codigo",
            "cnae_descricao",
            "municipio",
            "uf",
            "capital_centavos",
            "qtd_socios",
        }
        assert set(resultado.keys()) == esperado


class TestBuscar:
    def test_faz_um_get_na_url_do_cnpj(self) -> None:
        # Arrange
        pedidos: list[httpx.Request] = []

        def responder(pedido: httpx.Request) -> httpx.Response:
            pedidos.append(pedido)
            return httpx.Response(200, json={})

        # Act
        _buscar(responder)

        # Assert
        assert len(pedidos) == 1
        assert pedidos[0].method == "GET"
        assert str(pedidos[0].url) == f"{BASE_URL}/cnpj/v1/{CNPJ}"

    def test_barra_no_fim_da_base_url_nao_duplica(self) -> None:
        pedidos: list[httpx.Request] = []

        def responder(pedido: httpx.Request) -> httpx.Response:
            pedidos.append(pedido)
            return httpx.Response(200, json={})

        _buscar(responder, base_url=f"{BASE_URL}/")

        assert str(pedidos[0].url) == f"{BASE_URL}/cnpj/v1/{CNPJ}"

    def test_aplica_o_timeout_recebido(self) -> None:
        # sem prazo, uma fonte lenta trava o processo inteiro
        pedidos: list[httpx.Request] = []

        def responder(pedido: httpx.Request) -> httpx.Response:
            pedidos.append(pedido)
            return httpx.Response(200, json={})

        _buscar(responder, timeout=3)

        assert pedidos[0].extensions["timeout"]["read"] == 3

    @pytest.mark.parametrize("status", [400, 404, 429, 500])
    def test_devolve_erro_http_sem_interpretar(self, status: int) -> None:
        # 404, 429 e 5xx pedem reações diferentes; quem decide é o cliente.py
        resposta = _buscar(lambda _pedido: httpx.Response(status, json={"message": "erro"}))

        assert resposta.status_code == status

    def test_erro_de_rede_sobe_para_quem_chamou(self) -> None:
        def responder(pedido: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("simulado", request=pedido)

        with pytest.raises(httpx.ConnectTimeout):
            _buscar(responder)

    def test_resposta_pode_ser_normalizada(self, exemplo_brasilapi: dict[str, Any]) -> None:
        resposta = _buscar(lambda _pedido: httpx.Response(200, json=exemplo_brasilapi))

        assert normalizar(resposta.json()) == normalizar(exemplo_brasilapi)


class TestContratoComOBanco:
    def test_saida_do_adapter_grava_e_volta_igual(self, exemplo_brasilapi: dict[str, Any]) -> None:
        # Arrange
        dados = normalizar(exemplo_brasilapi)
        con = conectar(":memory:")

        try:
            # Act: `NOME` precisa passar no CHECK de `observacao.fonte`
            inserir_empresa_se_nao_existe(con, CNPJ, QUANDO)
            inserir_observacao(
                con,
                cnpj=CNPJ,
                dados=dados,
                fonte=NOME,
                coletado_em=QUANDO,
                bruto_json=json.dumps(exemplo_brasilapi),
            )
            [observacao] = observacoes_por_cnpj(con, CNPJ)
        finally:
            con.close()

        # Assert: toda chave do adapter existe como coluna, com o mesmo valor
        assert observacao["fonte"] == "brasilapi"
        assert {campo: observacao[campo] for campo in dados} == dados
