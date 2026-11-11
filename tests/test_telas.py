"""Testes do conteúdo das páginas (src/telas.py), sem passar pelo HTML."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.servico import (
    ORIGEM_CACHE,
    ORIGEM_CACHE_VENCIDO,
    Consulta,
    Historico,
    ItemDoPainel,
)
from src.telas import pagina_da_empresa, pagina_do_painel

AGORA = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)


def _observacao(**campos: Any) -> dict[str, Any]:
    base = {
        "cnpj": "11222333000181",
        "coletado_em": "2026-11-10 12:00:00",
        "razao_social": "ACME LTDA",
        "nome_fantasia": None,
        "situacao": "ATIVA",
        "data_situacao": "2009-09-02",
        "porte": "DEMAIS",
        "cnae_codigo": "8550301",
        "cnae_descricao": "Administração de caixas escolares",
        "municipio": "PORTO ALEGRE",
        "uf": "RS",
        "capital_centavos": 0,
        "qtd_socios": 1,
    }
    base.update(campos)
    return base


def _mudanca_de_situacao(quando: str) -> dict[str, Any]:
    return {"campo": "situacao", "de": "ATIVA", "para": "BAIXADA", "quando": quando}


def _pagina(
    origem: str = "brasilapi", mudancas: list[dict[str, Any]] | None = None, **campos: Any
) -> dict[str, Any]:
    consulta = Consulta(observacao=_observacao(**campos), origem=origem, idade_horas=0)
    historico = Historico(
        mudancas=mudancas or [], primeira_consulta="2026-01-01 10:00:00", acompanhando=False
    )
    return pagina_da_empresa(consulta, historico, agora=AGORA)


class TestDestaque:
    def test_mudanca_de_situacao_recente_vai_para_o_topo(self) -> None:
        pagina = _pagina(mudancas=[_mudanca_de_situacao("2026-11-08 09:00:00")])

        assert pagina["destaque"] == {
            "de": "ATIVA",
            "para": "BAIXADA",
            "quando": "08/11/2026, 06:00",
        }

    def test_mudanca_antiga_fica_so_na_linha_do_tempo(self) -> None:
        pagina = _pagina(mudancas=[_mudanca_de_situacao("2026-01-15 09:00:00")])

        assert pagina["destaque"] is None
        assert len(pagina["linha_do_tempo"]) == 1

    def test_linha_do_tempo_mostra_a_mais_recente_primeiro(self) -> None:
        mudancas = [
            {"campo": "porte", "de": "ME", "para": "EPP", "quando": "2026-02-01 09:00:00"},
            _mudanca_de_situacao("2026-11-08 09:00:00"),
        ]

        pagina = _pagina(mudancas=mudancas)

        assert [evento["rotulo"] for evento in pagina["linha_do_tempo"]] == ["Situação", "Porte"]


class TestOrigem:
    def test_cada_origem_tem_seu_tipo(self) -> None:
        assert _pagina(origem="brasilapi")["origem"]["tipo"] == "agora"
        assert _pagina(origem=ORIGEM_CACHE)["origem"]["tipo"] == "cache"
        assert _pagina(origem=ORIGEM_CACHE_VENCIDO)["origem"]["tipo"] == "fora"

    def test_horario_aparece_em_brasilia(self) -> None:
        assert _pagina()["origem"]["quando"] == "10/11/2026, 09:00"

    def test_so_o_dado_antigo_liga_o_aviso_de_fontes_fora(self) -> None:
        assert _pagina(origem=ORIGEM_CACHE_VENCIDO)["fontes_fora"] is True
        assert _pagina(origem=ORIGEM_CACHE)["fontes_fora"] is False


class TestCartao:
    def test_campos_ausentes_viram_nao_informado(self) -> None:
        cartao = {c["rotulo"]: c["valor"] for c in _pagina(municipio=None, uf=None)["cartao"]}

        assert cartao["Nome fantasia"] == "não informado"
        assert cartao["Município / UF"] == "não informado"

    def test_socios_por_extenso(self) -> None:
        def socios(n: int | None) -> str:
            cartao = {c["rotulo"]: c["valor"] for c in _pagina(qtd_socios=n)["cartao"]}
            return cartao["Quadro de sócios"]

        assert socios(0) == "Nenhum sócio informado"
        assert socios(1) == "1 sócio"
        assert socios(3) == "3 sócios"


def _item(estado: str, **campos: Any) -> ItemDoPainel:
    return ItemDoPainel(
        cnpj="11222333000181",
        observacao=_observacao(**campos),
        ultima_mudanca=None,
        primeira_consulta="2026-01-01 10:00:00",
        estado=estado,
    )


class TestPainel:
    def test_conta_por_estado_e_filtra(self) -> None:
        itens = [_item("mudanca"), _item("falha"), _item("ok"), _item("ok")]

        pagina = pagina_do_painel(itens, "ok")

        assert (pagina["total"], pagina["mudancas"], pagina["falhas"]) == (4, 1, 1)
        assert [f["quantidade"] for f in pagina["filtros"]] == [4, 1, 1, 2]
        assert len(pagina["itens"]) == 2

    def test_filtro_desconhecido_mostra_todas(self) -> None:
        pagina = pagina_do_painel([_item("ok")], "qualquer")

        assert [f["valor"] for f in pagina["filtros"] if f["ativo"]] == ["todas"]
        assert len(pagina["itens"]) == 1

    def test_sem_novidade_diz_desde_quando(self) -> None:
        [item] = pagina_do_painel([_item("ok")])["itens"]

        assert item["texto"] == "Sem mudanças desde a primeira consulta, em 01/01/2026."
