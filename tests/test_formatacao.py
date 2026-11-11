"""Testes da formatação compartilhada pela linha de comando e pela tela."""

from __future__ import annotations

import pytest

from src.formatacao import (
    ROTULOS,
    campos_da_ficha,
    data_br,
    data_hora_br,
    descrever_origem,
    formatar_capital,
    formatar_cnae,
    gravidade_da_situacao,
)
from src.servico import ORIGEM_CACHE, ORIGEM_CACHE_VENCIDO, Consulta


class TestFormatacao:
    @pytest.mark.parametrize(
        ("centavos", "esperado"),
        [
            (0, "R$ 0,00"),
            (5, "R$ 0,05"),
            (123456789, "R$ 1.234.567,89"),
            (20543196000000, "R$ 205.431.960.000,00"),
            (None, "não informado"),
        ],
    )
    def test_capital_em_reais(self, centavos: int | None, esperado: str) -> None:
        assert formatar_capital(centavos) == esperado

    @pytest.mark.parametrize(
        ("origem", "idade", "esperado"),
        [
            ("brasilapi", 0, "consultado agora na BrasilAPI"),
            (ORIGEM_CACHE, 0.5, "do cache, há menos de 1 hora"),
            (ORIGEM_CACHE, 1, "do cache, há 1 hora"),
            (ORIGEM_CACHE, 6.5, "do cache, há 6 horas"),
            (ORIGEM_CACHE_VENCIDO, 72, "consultado há 3 dias, as fontes estão fora do ar agora"),
        ],
    )
    def test_origem_por_extenso(self, origem: str, idade: float, esperado: str) -> None:
        consulta = Consulta(observacao={}, origem=origem, idade_horas=idade)

        assert descrever_origem(consulta) == esperado

    def test_ficha_mostra_cada_campo_formatado_em_ordem(self) -> None:
        observacao = {campo: None for campo in ROTULOS}
        observacao.update(cnpj="11222333000181", razao_social="ACME LTDA", capital_centavos=150)

        campos = dict(campos_da_ficha(observacao))

        assert list(campos)[:3] == ["CNPJ", "Razão social", "Nome fantasia"]
        assert campos["CNPJ"] == "11.222.333/0001-81"
        assert campos["Capital social"] == "R$ 1,50"
        assert campos["Situação"] == "não informado"

    def test_cnae_no_formato_da_receita(self) -> None:
        assert formatar_cnae("8550301") == "85.50-3-01"
        assert formatar_cnae("0161099") == "01.61-0-99"
        assert formatar_cnae(None) == "não informado"

    def test_datas_no_formato_brasileiro(self) -> None:
        assert data_br("2009-09-02") == "02/09/2009"
        assert data_br(None) == "não informado"
        # gravado em UTC, mostrado em Brasília (UTC-3)
        assert data_hora_br("2026-11-10 02:30:00") == "09/11/2026, 23:30"

    def test_gravidade_de_cada_situacao(self) -> None:
        assert gravidade_da_situacao("ATIVA") == "ok"
        assert gravidade_da_situacao("SUSPENSA") == "alerta"
        assert gravidade_da_situacao("BAIXADA") == "grave"
        assert gravidade_da_situacao(None) == "neutro"
