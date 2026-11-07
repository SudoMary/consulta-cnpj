"""Testes da camada de repositório (src/repo.py).

Todos usam SQLite em memória — sem rede, sem arquivo em disco.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.db import conectar
from src.repo import (
    atualizar_ultima_consulta,
    empresa_por_cnpj,
    inserir_empresa_se_nao_existe,
    inserir_observacao,
    observacao_mais_nova,
    observacoes_por_cnpj,
    registrar_falha,
)

CNPJ = "11222333000181"
OUTRO_CNPJ = "11444777000161"
T0 = "2026-01-01 10:00:00"
T1 = "2026-01-02 10:00:00"
T2 = "2026-01-03 10:00:00"


@pytest.fixture
def con() -> sqlite3.Connection:
    c = conectar(":memory:")
    yield c
    c.close()


class TestInserirEmpresa:
    def test_insere_empresa_nova(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        row = con.execute("SELECT cnpj FROM empresa WHERE cnpj = ?", (CNPJ,)).fetchone()
        assert row is not None
        assert row["cnpj"] == CNPJ

    def test_inserir_duas_vezes_nao_duplica(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        inserir_empresa_se_nao_existe(con, CNPJ, T1)

        total = con.execute("SELECT COUNT(*) FROM empresa").fetchone()[0]
        assert total == 1

    def test_inserir_duas_vezes_preserva_primeira_consulta(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        inserir_empresa_se_nao_existe(con, CNPJ, T1)

        row = con.execute(
            "SELECT primeira_consulta, ultima_consulta FROM empresa WHERE cnpj = ?", (CNPJ,)
        ).fetchone()
        assert row["primeira_consulta"] == T0
        assert row["ultima_consulta"] == T0  # nao muda so por re-inserir


class TestInserirObservacao:
    def test_insere_e_devolve_id(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        obs_id = inserir_observacao(
            con,
            cnpj=CNPJ,
            dados={"razao_social": "ACME LTDA", "situacao": "ATIVA"},
            fonte="brasilapi",
            coletado_em=T0,
            bruto_json='{"razao_social":"ACME LTDA","situacao":"ATIVA"}',
        )

        assert obs_id > 0
        row = con.execute("SELECT razao_social FROM observacao WHERE id = ?", (obs_id,)).fetchone()
        assert row["razao_social"] == "ACME LTDA"

    def test_campos_ausentes_viram_none(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        obs_id = inserir_observacao(
            con,
            cnpj=CNPJ,
            dados={},  # vazio
            fonte="brasilapi",
            coletado_em=T0,
            bruto_json="{}",
        )

        row = con.execute(
            "SELECT razao_social, situacao, capital_centavos FROM observacao WHERE id = ?",
            (obs_id,),
        ).fetchone()
        assert row["razao_social"] is None
        assert row["situacao"] is None
        assert row["capital_centavos"] is None

    def test_bruto_json_preservado_na_integra(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        bruto = '{"extra_que_nao_extraimos": "valor", "situacao": "ATIVA"}'

        obs_id = inserir_observacao(
            con,
            cnpj=CNPJ,
            dados={"situacao": "ATIVA"},
            fonte="brasilapi",
            coletado_em=T0,
            bruto_json=bruto,
        )

        row = con.execute("SELECT bruto_json FROM observacao WHERE id = ?", (obs_id,)).fetchone()
        assert row["bruto_json"] == bruto


class TestObservacoesPorCnpj:
    def test_lista_vazia_quando_nao_ha_observacoes(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        assert observacoes_por_cnpj(con, CNPJ) == []

    def test_retorna_em_ordem_de_coletado_em(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        # insiro fora de ordem de propósito
        for quando in (T2, T0, T1):
            inserir_observacao(
                con,
                cnpj=CNPJ,
                dados={"situacao": "ATIVA"},
                fonte="brasilapi",
                coletado_em=quando,
                bruto_json="{}",
            )

        resultado = observacoes_por_cnpj(con, CNPJ)

        assert [r["coletado_em"] for r in resultado] == [T0, T1, T2]

    def test_so_observacoes_do_cnpj_correto(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        inserir_empresa_se_nao_existe(con, OUTRO_CNPJ, T0)
        inserir_observacao(
            con,
            cnpj=CNPJ,
            dados={},
            fonte="brasilapi",
            coletado_em=T0,
            bruto_json="{}",
        )
        inserir_observacao(
            con,
            cnpj=OUTRO_CNPJ,
            dados={},
            fonte="brasilapi",
            coletado_em=T0,
            bruto_json="{}",
        )

        resultado = observacoes_por_cnpj(con, CNPJ)

        assert len(resultado) == 1
        assert resultado[0]["cnpj"] == CNPJ


class TestObservacaoMaisNova:
    def _gravar(self, con: sqlite3.Connection, cnpj: str, quando: str, situacao: str) -> None:
        inserir_empresa_se_nao_existe(con, cnpj, T0)
        inserir_observacao(
            con,
            cnpj=cnpj,
            dados={"situacao": situacao},
            fonte="brasilapi",
            coletado_em=quando,
            bruto_json="{}",
        )

    def test_none_quando_nao_ha_observacoes(self, con: sqlite3.Connection) -> None:
        assert observacao_mais_nova(con, CNPJ) is None

    def test_devolve_a_de_coleta_mais_recente(self, con: sqlite3.Connection) -> None:
        # insiro fora de ordem de propósito
        for quando in (T2, T0, T1):
            self._gravar(con, CNPJ, quando, "ATIVA")

        assert observacao_mais_nova(con, CNPJ)["coletado_em"] == T2

    def test_no_mesmo_segundo_vence_a_ultima_gravada(self, con: sqlite3.Connection) -> None:
        self._gravar(con, CNPJ, T0, "ATIVA")
        self._gravar(con, CNPJ, T0, "BAIXADA")

        assert observacao_mais_nova(con, CNPJ)["situacao"] == "BAIXADA"

    def test_ignora_outros_cnpjs(self, con: sqlite3.Connection) -> None:
        self._gravar(con, OUTRO_CNPJ, T2, "BAIXADA")

        assert observacao_mais_nova(con, CNPJ) is None


class TestAtualizarUltimaConsulta:
    def test_atualiza_campo(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        atualizar_ultima_consulta(con, CNPJ, T2)

        row = con.execute("SELECT ultima_consulta FROM empresa WHERE cnpj = ?", (CNPJ,)).fetchone()
        assert row["ultima_consulta"] == T2


class TestRegistrarFalha:
    def test_grava_falha_sem_empresa_cadastrada(self, con: sqlite3.Connection) -> None:
        # a falha pode ocorrer antes da empresa existir no banco
        registrar_falha(
            con,
            cnpj=CNPJ,
            fonte="brasilapi",
            motivo="timeout",
            ocorrido_em=T0,
        )

        row = con.execute("SELECT motivo FROM falha_coleta WHERE cnpj = ?", (CNPJ,)).fetchone()
        assert row["motivo"] == "timeout"


class TestEmpresaPorCnpj:
    def test_none_quando_nao_existe(self, con: sqlite3.Connection) -> None:
        assert empresa_por_cnpj(con, CNPJ) is None

    def test_dict_quando_existe(self, con: sqlite3.Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        resultado = empresa_por_cnpj(con, CNPJ)

        assert resultado is not None
        assert resultado["cnpj"] == CNPJ
        assert resultado["acompanhando"] == 0
