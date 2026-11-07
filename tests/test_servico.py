"""Testes das regras do serviço: cache, degradação e detecção de mudança.

`coletar` é falso: conta as chamadas e segue um roteiro, então cada teste prova
quantas vezes a rede teria sido usada, sem tocar nela. O banco é SQLite em
memória, e o relógio é passado como argumento.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.cliente import CnpjNaoEncontrado, Coleta, ErroDeFonte, TodasAsFontesFalharam
from src.db import conectar
from src.repo import (
    empresa_por_cnpj,
    inserir_empresa_se_nao_existe,
    inserir_observacao,
    observacoes_por_cnpj,
)
from src.servico import (
    ORIGEM_CACHE,
    ORIGEM_CACHE_VENCIDO,
    Consulta,
    RegraDeNegocio,
    consultar,
    mudancas,
)

CNPJ = "11222333000181"
TTL_HORAS = 24
AGORA = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
AGORA_TEXTO = "2026-11-06 12:00:00"
ERRO_500 = ErroDeFonte("brasilapi", "HTTP 500")


class ColetaFalsa:
    """Faz o papel de `consultar_externo`: conta as chamadas e segue um roteiro.

    Uma chamada além do roteiro estoura `IndexError` e reprova o teste.
    """

    def __init__(self, *passos: Coleta | Exception) -> None:
        self.passos = list(passos)
        self.chamadas = 0

    def __call__(self, cnpj: str) -> Coleta:
        self.chamadas += 1
        passo = self.passos.pop(0)
        if isinstance(passo, Exception):
            raise passo
        return passo


def _coleta(
    situacao: str = "ATIVA",
    *,
    fonte: str = "brasilapi",
    erros: tuple[ErroDeFonte, ...] = (),
) -> Coleta:
    dados = {"razao_social": "ACME LTDA", "situacao": situacao}
    return Coleta(dados=dados, fonte=fonte, bruto_json='{"bruto": true}', erros=erros)


@pytest.fixture
def con() -> Iterator[sqlite3.Connection]:
    c = conectar(":memory:")
    yield c
    c.close()


def _consultar(
    con: sqlite3.Connection,
    coletar: ColetaFalsa,
    *,
    agora: datetime = AGORA,
    forcar: bool = False,
    cnpj: str = CNPJ,
) -> Consulta:
    return consultar(
        cnpj, con=con, coletar=coletar, ttl_horas=TTL_HORAS, forcar=forcar, agora=agora
    )


def _falhas(con: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    linhas = con.execute("SELECT cnpj, ocorrido_em, fonte, motivo FROM falha_coleta ORDER BY id")
    return [tuple(linha) for linha in linhas]


def _gravar_observacao(
    con: sqlite3.Connection, quando: str, *, fonte: str = "brasilapi", **dados: Any
) -> None:
    inserir_empresa_se_nao_existe(con, CNPJ, quando)
    inserir_observacao(
        con, cnpj=CNPJ, dados=dados, fonte=fonte, coletado_em=quando, bruto_json="{}"
    )


class TestValidacaoAntesDaRede:
    @pytest.mark.parametrize("cnpj", ["11222333000182", "123", "", "00000000000000"])
    def test_cnpj_invalido_nao_chama_a_rede(self, con: sqlite3.Connection, cnpj: str) -> None:
        coletar = ColetaFalsa()

        with pytest.raises(RegraDeNegocio, match="CNPJ inválido"):
            _consultar(con, coletar, cnpj=cnpj)

        assert coletar.chamadas == 0

    def test_aceita_cnpj_com_mascara(self, con: sqlite3.Connection) -> None:
        consulta = _consultar(con, ColetaFalsa(_coleta()), cnpj="11.222.333/0001-81")

        assert consulta.observacao["cnpj"] == CNPJ


class TestPrimeiraConsulta:
    def test_grava_empresa_e_observacao(self, con: sqlite3.Connection) -> None:
        # Act
        consulta = _consultar(con, ColetaFalsa(_coleta()))

        # Assert
        assert consulta.origem == "brasilapi"
        assert consulta.idade_horas == 0
        assert consulta.observacao["razao_social"] == "ACME LTDA"
        assert consulta.observacao["coletado_em"] == AGORA_TEXTO
        assert consulta.observacao["bruto_json"] == '{"bruto": true}'
        assert empresa_por_cnpj(con, CNPJ)["primeira_consulta"] == AGORA_TEXTO

    def test_origem_diz_qual_fonte_respondeu(self, con: sqlite3.Connection) -> None:
        consulta = _consultar(con, ColetaFalsa(_coleta(fonte="minhareceita")))

        assert consulta.origem == "minhareceita"
        assert consulta.observacao["fonte"] == "minhareceita"

    def test_gravacao_sobrevive_ao_fechar_a_conexao(self, tmp_path: Path) -> None:
        # Sem commit, tudo sumiria ao fechar: o teste em memória não enxerga isso.
        caminho = str(tmp_path / "teste.db")
        con = conectar(caminho)
        _consultar(con, ColetaFalsa(_coleta()))
        con.close()

        outra = conectar(caminho)
        try:
            assert len(observacoes_por_cnpj(outra, CNPJ)) == 1
        finally:
            outra.close()


class TestCache:
    def test_duas_consultas_seguidas_fazem_uma_chamada(self, con: sqlite3.Connection) -> None:
        # Arrange
        coletar = ColetaFalsa(_coleta())
        _consultar(con, coletar)

        # Act
        depois = _consultar(con, coletar, agora=AGORA + timedelta(hours=6))

        # Assert
        assert coletar.chamadas == 1
        assert depois.origem == ORIGEM_CACHE
        assert depois.idade_horas == 6
        assert len(observacoes_por_cnpj(con, CNPJ)) == 1

    def test_cache_vencido_chama_de_novo_e_acrescenta_observacao(
        self, con: sqlite3.Connection
    ) -> None:
        coletar = ColetaFalsa(_coleta(), _coleta())
        _consultar(con, coletar)

        depois = _consultar(con, coletar, agora=AGORA + timedelta(hours=TTL_HORAS))

        assert coletar.chamadas == 2
        assert depois.origem == "brasilapi"
        assert len(observacoes_por_cnpj(con, CNPJ)) == 2

    def test_forcar_ignora_o_cache(self, con: sqlite3.Connection) -> None:
        coletar = ColetaFalsa(_coleta(), _coleta())
        _consultar(con, coletar)

        depois = _consultar(con, coletar, agora=AGORA + timedelta(minutes=1), forcar=True)

        assert coletar.chamadas == 2
        assert depois.origem == "brasilapi"

    def test_nova_coleta_atualiza_ultima_consulta_e_preserva_a_primeira(
        self, con: sqlite3.Connection
    ) -> None:
        coletar = ColetaFalsa(_coleta(), _coleta())
        _consultar(con, coletar)

        _consultar(con, coletar, agora=AGORA + timedelta(days=2))

        empresa = empresa_por_cnpj(con, CNPJ)
        assert empresa["primeira_consulta"] == AGORA_TEXTO
        assert empresa["ultima_consulta"] == "2026-11-08 12:00:00"


class TestDegradacao:
    def test_fontes_fora_com_observacao_antiga_devolve_a_antiga(
        self, con: sqlite3.Connection
    ) -> None:
        # Arrange
        coletar = ColetaFalsa(_coleta(), TodasAsFontesFalharam([ERRO_500]))
        _consultar(con, coletar)

        # Act
        depois = _consultar(con, coletar, agora=AGORA + timedelta(days=3))

        # Assert
        assert depois.origem == ORIGEM_CACHE_VENCIDO
        assert depois.idade_horas == 72
        assert depois.observacao["razao_social"] == "ACME LTDA"
        assert len(observacoes_por_cnpj(con, CNPJ)) == 1

    def test_degradacao_registra_cada_falha(self, con: sqlite3.Connection) -> None:
        erros = [ERRO_500, ErroDeFonte("minhareceita", "timeout")]
        coletar = ColetaFalsa(_coleta(), TodasAsFontesFalharam(erros))
        _consultar(con, coletar)

        _consultar(con, coletar, agora=AGORA + timedelta(days=3))

        assert _falhas(con) == [
            (CNPJ, "2026-11-09 12:00:00", "brasilapi", "HTTP 500"),
            (CNPJ, "2026-11-09 12:00:00", "minhareceita", "timeout"),
        ]

    def test_sem_observacao_o_erro_sobe_e_a_falha_fica_registrada(self, tmp_path: Path) -> None:
        # Em arquivo: a falha precisa estar gravada mesmo com a exceção subindo.
        caminho = str(tmp_path / "teste.db")
        con = conectar(caminho)
        with pytest.raises(TodasAsFontesFalharam):
            _consultar(con, ColetaFalsa(TodasAsFontesFalharam([ERRO_500])))
        con.close()

        outra = conectar(caminho)
        try:
            assert _falhas(outra) == [(CNPJ, AGORA_TEXTO, "brasilapi", "HTTP 500")]
            assert empresa_por_cnpj(outra, CNPJ) is None
        finally:
            outra.close()

    def test_falha_da_primaria_e_registrada_quando_a_reserva_resolve(
        self, con: sqlite3.Connection
    ) -> None:
        coleta = _coleta(fonte="minhareceita", erros=(ERRO_500,))

        _consultar(con, ColetaFalsa(coleta))

        assert _falhas(con) == [(CNPJ, AGORA_TEXTO, "brasilapi", "HTTP 500")]


class TestNaoEncontrado:
    def test_404_nao_grava_nada_nem_conta_como_falha(self, con: sqlite3.Connection) -> None:
        with pytest.raises(CnpjNaoEncontrado):
            _consultar(con, ColetaFalsa(CnpjNaoEncontrado(CNPJ)))

        assert empresa_por_cnpj(con, CNPJ) is None
        assert _falhas(con) == []


class TestMudancas:
    def test_situacao_diferente_gera_uma_mudanca(self, con: sqlite3.Connection) -> None:
        _gravar_observacao(con, "2026-03-01 10:00:00", situacao="ATIVA")
        _gravar_observacao(con, "2026-07-15 10:00:00", situacao="BAIXADA")

        assert mudancas(con, CNPJ) == [
            {
                "campo": "situacao",
                "de": "ATIVA",
                "para": "BAIXADA",
                "quando": "2026-07-15 10:00:00",
            }
        ]

    def test_observacoes_identicas_nao_geram_mudanca(self, con: sqlite3.Connection) -> None:
        _gravar_observacao(con, "2026-03-01 10:00:00", situacao="ATIVA")
        _gravar_observacao(con, "2026-07-15 10:00:00", situacao="ATIVA")

        assert mudancas(con, CNPJ) == []

    def test_uma_observacao_so_nao_gera_mudanca(self, con: sqlite3.Connection) -> None:
        _gravar_observacao(con, "2026-03-01 10:00:00", situacao="ATIVA")

        assert mudancas(con, CNPJ) == []

    def test_sem_observacoes_nao_gera_mudanca(self, con: sqlite3.Connection) -> None:
        assert mudancas(con, CNPJ) == []

    def test_campo_fora_da_lista_nao_e_mudanca(self, con: sqlite3.Connection) -> None:
        # nome_fantasia e capital não são vigiados: decisão de negócio
        _gravar_observacao(con, "2026-03-01 10:00:00", nome_fantasia="A", capital_centavos=1)
        _gravar_observacao(con, "2026-07-15 10:00:00", nome_fantasia="B", capital_centavos=2)

        assert mudancas(con, CNPJ) == []

    def test_trocar_de_fonte_nao_e_mudanca(self, con: sqlite3.Connection) -> None:
        _gravar_observacao(con, "2026-03-01 10:00:00", fonte="brasilapi", situacao="ATIVA")
        _gravar_observacao(con, "2026-07-15 10:00:00", fonte="minhareceita", situacao="ATIVA")

        assert mudancas(con, CNPJ) == []

    # Lista escrita à mão de propósito: se viesse de `CAMPOS_VIGIADOS`, tirar um
    # campo do código também o tiraria do teste, e nada reprovaria.
    @pytest.mark.parametrize(
        "campo",
        ["razao_social", "situacao", "porte", "cnae_codigo", "municipio", "uf", "qtd_socios"],
    )
    def test_cada_campo_vigiado_e_detectado(self, con: sqlite3.Connection, campo: str) -> None:
        _gravar_observacao(con, "2026-03-01 10:00:00", **{campo: 1})
        _gravar_observacao(con, "2026-07-15 10:00:00", **{campo: 2})

        assert [mudanca["campo"] for mudanca in mudancas(con, CNPJ)] == [campo]

    def test_mudancas_saem_em_ordem_cronologica(self, con: sqlite3.Connection) -> None:
        # inseridas fora de ordem de propósito
        _gravar_observacao(con, "2026-09-01 10:00:00", situacao="BAIXADA")
        _gravar_observacao(con, "2026-03-01 10:00:00", situacao="ATIVA")
        _gravar_observacao(con, "2026-07-15 10:00:00", situacao="SUSPENSA")

        resultado = mudancas(con, CNPJ)

        assert [(m["de"], m["para"]) for m in resultado] == [
            ("ATIVA", "SUSPENSA"),
            ("SUSPENSA", "BAIXADA"),
        ]
