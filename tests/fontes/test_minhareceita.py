"""Testes da normalização do JSON da Minha Receita.

Partem do JSON REAL salvo em `dados/exemplo_minhareceita.json`. O contrato de
`buscar`, comum às fontes, está em `test_contrato.py`.
"""

from __future__ import annotations

from typing import Any

from src.fontes.minhareceita import normalizar


class TestNormalizar:
    def test_traduz_a_resposta_real(self, exemplo_minhareceita: dict[str, Any]) -> None:
        resultado = normalizar(exemplo_minhareceita)

        assert resultado == {
            "razao_social": (
                "CAIXA ESCOLAR DA ESCOLA ESTADUAL DE ENSINO FUNDAMENTAL JOSEFINA JACQUES NORONHA"
            ),
            "nome_fantasia": "CAIXA ESCOLA DA ESCOLA ESTADUAL DE ENSINO FUNDAMENTAL J",
            "situacao": "ATIVA",
            "data_situacao": "2009-09-02",
            "porte": "DEMAIS",
            "cnae_codigo": "8550301",
            "cnae_descricao": "Administração de caixas escolares",
            "municipio": "SAO SEBASTIAO DO CAI",
            "uf": "RS",
            "capital_centavos": 0,
            "qtd_socios": 1,
        }

    def test_preserva_zero_do_cnae_e_trata_fantasia_vazia(self) -> None:
        # valores reais da SLC Agrícola na Minha Receita
        resultado = normalizar({"cnae_fiscal": 161099, "nome_fantasia": ""})

        assert resultado["cnae_codigo"] == "0161099"
        assert resultado["nome_fantasia"] is None

    def test_campos_ausentes_viram_none(self) -> None:
        resultado = normalizar({})

        assert set(resultado.values()) == {None}
