"""Testes da normalização do JSON da BrasilAPI.

Cada teste parte do JSON REAL salvo em `dados/exemplo_brasilapi.json`.
Nenhum nome de campo aqui foi inventado — todos existem no fixture. O contrato
de `buscar`, comum às fontes, está em `test_contrato.py`.
"""

from __future__ import annotations

from typing import Any

from fontes.brasilapi import normalizar


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
