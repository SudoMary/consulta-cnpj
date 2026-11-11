"""Testes da camada de repositório (src/repo.py).

Rodam no SQLite e, com `TEST_DATABASE_URL` definida, também no PostgreSQL.
Cada teste roda dentro de uma transação, como o serviço faz.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from src.repo import (
    atualizar_ultima_consulta,
    cnpjs_acompanhados,
    empresa_por_cnpj,
    inserir_empresa_se_nao_existe,
    inserir_observacao,
    marcar_acompanhamento,
    observacao_mais_nova,
    observacoes_por_cnpj,
    registrar_falha,
    ultima_falha,
)

CNPJ = "11222333000181"
OUTRO_CNPJ = "11444777000161"
T0 = "2026-01-01 10:00:00"
T1 = "2026-01-02 10:00:00"
T2 = "2026-01-03 10:00:00"


@pytest.fixture
def con(motor: Engine) -> Iterator[Connection]:
    with motor.begin() as conexao:
        yield conexao


def _linha(con: Connection, sql: str, **parametros: Any) -> dict[str, Any] | None:
    linha = con.execute(text(sql), parametros).mappings().first()
    return dict(linha) if linha else None


class TestInserirEmpresa:
    def test_insere_empresa_nova(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        row = _linha(con, "SELECT cnpj FROM empresa WHERE cnpj = :cnpj", cnpj=CNPJ)
        assert row is not None
        assert row["cnpj"] == CNPJ

    def test_inserir_duas_vezes_nao_duplica(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        inserir_empresa_se_nao_existe(con, CNPJ, T1)

        total = con.execute(text("SELECT COUNT(*) FROM empresa")).scalar_one()
        assert total == 1

    def test_inserir_duas_vezes_preserva_primeira_consulta(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        inserir_empresa_se_nao_existe(con, CNPJ, T1)

        row = _linha(
            con,
            "SELECT primeira_consulta, ultima_consulta FROM empresa WHERE cnpj = :cnpj",
            cnpj=CNPJ,
        )
        assert row["primeira_consulta"] == T0
        assert row["ultima_consulta"] == T0  # nao muda so por re-inserir


class TestInserirObservacao:
    def test_insere_e_devolve_id(self, con: Connection) -> None:
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
        row = _linha(con, "SELECT razao_social FROM observacao WHERE id = :id", id=obs_id)
        assert row["razao_social"] == "ACME LTDA"

    def test_campos_ausentes_viram_none(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        obs_id = inserir_observacao(
            con,
            cnpj=CNPJ,
            dados={},  # vazio
            fonte="brasilapi",
            coletado_em=T0,
            bruto_json="{}",
        )

        row = _linha(
            con,
            "SELECT razao_social, situacao, capital_centavos FROM observacao WHERE id = :id",
            id=obs_id,
        )
        assert row["razao_social"] is None
        assert row["situacao"] is None
        assert row["capital_centavos"] is None

    def test_bruto_json_preservado_na_integra(self, con: Connection) -> None:
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

        row = _linha(con, "SELECT bruto_json FROM observacao WHERE id = :id", id=obs_id)
        assert row["bruto_json"] == bruto


class TestObservacoesPorCnpj:
    def test_lista_vazia_quando_nao_ha_observacoes(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        assert observacoes_por_cnpj(con, CNPJ) == []

    def test_retorna_em_ordem_de_coletado_em(self, con: Connection) -> None:
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

    def test_so_observacoes_do_cnpj_correto(self, con: Connection) -> None:
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
    def _gravar(self, con: Connection, cnpj: str, quando: str, situacao: str) -> None:
        inserir_empresa_se_nao_existe(con, cnpj, T0)
        inserir_observacao(
            con,
            cnpj=cnpj,
            dados={"situacao": situacao},
            fonte="brasilapi",
            coletado_em=quando,
            bruto_json="{}",
        )

    def test_none_quando_nao_ha_observacoes(self, con: Connection) -> None:
        assert observacao_mais_nova(con, CNPJ) is None

    def test_devolve_a_de_coleta_mais_recente(self, con: Connection) -> None:
        # insiro fora de ordem de propósito
        for quando in (T2, T0, T1):
            self._gravar(con, CNPJ, quando, "ATIVA")

        assert observacao_mais_nova(con, CNPJ)["coletado_em"] == T2

    def test_no_mesmo_segundo_vence_a_ultima_gravada(self, con: Connection) -> None:
        self._gravar(con, CNPJ, T0, "ATIVA")
        self._gravar(con, CNPJ, T0, "BAIXADA")

        assert observacao_mais_nova(con, CNPJ)["situacao"] == "BAIXADA"

    def test_ignora_outros_cnpjs(self, con: Connection) -> None:
        self._gravar(con, OUTRO_CNPJ, T2, "BAIXADA")

        assert observacao_mais_nova(con, CNPJ) is None


class TestAtualizarUltimaConsulta:
    def test_atualiza_campo(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        atualizar_ultima_consulta(con, CNPJ, T2)

        row = _linha(con, "SELECT ultima_consulta FROM empresa WHERE cnpj = :cnpj", cnpj=CNPJ)
        assert row["ultima_consulta"] == T2


class TestRegistrarFalha:
    def test_grava_falha_sem_empresa_cadastrada(self, con: Connection) -> None:
        # a falha pode ocorrer antes da empresa existir no banco
        registrar_falha(
            con,
            cnpj=CNPJ,
            fonte="brasilapi",
            motivo="timeout",
            ocorrido_em=T0,
        )

        row = _linha(con, "SELECT motivo FROM falha_coleta WHERE cnpj = :cnpj", cnpj=CNPJ)
        assert row["motivo"] == "timeout"


class TestEmpresaPorCnpj:
    def test_none_quando_nao_existe(self, con: Connection) -> None:
        assert empresa_por_cnpj(con, CNPJ) is None

    def test_dict_quando_existe(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        resultado = empresa_por_cnpj(con, CNPJ)

        assert resultado is not None
        assert resultado["cnpj"] == CNPJ
        assert resultado["acompanhando"] == 0


class TestAcompanhamento:
    def test_empresa_nova_nao_e_acompanhada(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)

        assert cnpjs_acompanhados(con) == []

    def test_marcar_inclui_so_a_empresa_marcada(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        inserir_empresa_se_nao_existe(con, OUTRO_CNPJ, T0)

        marcar_acompanhamento(con, OUTRO_CNPJ, acompanhando=True)

        assert cnpjs_acompanhados(con) == [OUTRO_CNPJ]

    def test_desmarcar_tira_da_lista(self, con: Connection) -> None:
        inserir_empresa_se_nao_existe(con, CNPJ, T0)
        marcar_acompanhamento(con, CNPJ, acompanhando=True)

        marcar_acompanhamento(con, CNPJ, acompanhando=False)

        assert cnpjs_acompanhados(con) == []

    def test_lista_sai_em_ordem_de_cnpj(self, con: Connection) -> None:
        for cnpj in (OUTRO_CNPJ, CNPJ):
            inserir_empresa_se_nao_existe(con, cnpj, T0)
            marcar_acompanhamento(con, cnpj, acompanhando=True)

        assert cnpjs_acompanhados(con) == [CNPJ, OUTRO_CNPJ]


class TestUltimaFalha:
    def test_none_quando_nunca_falhou(self, con: Connection) -> None:
        assert ultima_falha(con, CNPJ) is None

    def test_devolve_a_mais_recente(self, con: Connection) -> None:
        for quando, motivo in ((T0, "timeout"), (T2, "HTTP 500"), (T1, "HTTP 503")):
            registrar_falha(con, cnpj=CNPJ, fonte="brasilapi", motivo=motivo, ocorrido_em=quando)

        assert ultima_falha(con, CNPJ)["motivo"] == "HTTP 500"
