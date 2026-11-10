"""Testes da recoleta diária (src/coletor.py).

Mesma ideia dos testes do serviço: `coletar` é falso e conta as chamadas, o
relógio é passado como argumento, e o banco roda no SQLite e, com
`TEST_DATABASE_URL` definida, também no PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine

from src.cliente import CnpjNaoEncontrado, ErroDeFonte, TodasAsFontesFalharam
from src.coletor import Resumo, coletar_acompanhadas, main
from src.db import criar_motor
from src.repo import (
    inserir_empresa_se_nao_existe,
    inserir_observacao,
    marcar_acompanhamento,
    observacoes_por_cnpj,
)
from tests.falsos import ColetaFalsa, coleta

CNPJ = "11222333000181"
OUTRO = "11444777000161"
ONTEM = "2026-11-09 09:00:00"
HOJE = datetime(2026, 11, 10, 9, 0, 0, tzinfo=UTC)
ERRO = ErroDeFonte("brasilapi", "HTTP 500")


def _acompanhar(motor: Engine, cnpj: str, coletado_em: str = ONTEM) -> None:
    """Empresa acompanhada, com uma observação já gravada."""
    with motor.begin() as con:
        inserir_empresa_se_nao_existe(con, cnpj, coletado_em)
        inserir_observacao(
            con,
            cnpj=cnpj,
            dados={"razao_social": "ACME LTDA", "situacao": "ATIVA"},
            fonte="brasilapi",
            coletado_em=coletado_em,
            bruto_json="{}",
        )
        marcar_acompanhamento(con, cnpj, acompanhando=True)


def _rodar(motor: Engine, coletar: ColetaFalsa, agora: datetime = HOJE) -> Resumo:
    return coletar_acompanhadas(motor=motor, coletar=coletar, ttl_horas=24, agora=agora)


def _observacoes(motor: Engine, cnpj: str) -> list[dict[str, Any]]:
    with motor.connect() as con:
        return observacoes_por_cnpj(con, cnpj)


class TestColetaDiaria:
    def test_coleta_so_as_empresas_acompanhadas(self, motor: Engine) -> None:
        # Arrange: OUTRO foi consultada, mas não é acompanhada
        _acompanhar(motor, CNPJ)
        with motor.begin() as con:
            inserir_empresa_se_nao_existe(con, OUTRO, ONTEM)
        coletar = ColetaFalsa(coleta())

        # Act
        resumo = _rodar(motor, coletar)

        # Assert
        assert coletar.cnpjs == [CNPJ]
        assert resumo == Resumo(coletadas=[CNPJ], puladas=[], falhas=[])
        assert len(_observacoes(motor, CNPJ)) == 2

    def test_coleta_mesmo_com_o_cache_ainda_valido(self, motor: Engine) -> None:
        # A última coleta foi há 20 horas: para a tela o cache ainda vale, mas
        # a recoleta diária precisa de uma observação por dia.
        _acompanhar(motor, CNPJ, coletado_em="2026-11-09 13:00:00")
        coletar = ColetaFalsa(coleta())

        _rodar(motor, coletar)

        assert coletar.chamadas == 1
        assert len(_observacoes(motor, CNPJ)) == 2

    def test_rodar_duas_vezes_no_mesmo_dia_nao_duplica(self, motor: Engine) -> None:
        _acompanhar(motor, CNPJ)
        coletar = ColetaFalsa(coleta())
        _rodar(motor, coletar)

        segunda = _rodar(motor, coletar, agora=HOJE + timedelta(hours=5))

        assert coletar.chamadas == 1
        assert segunda == Resumo(coletadas=[], puladas=[CNPJ], falhas=[])
        assert len(_observacoes(motor, CNPJ)) == 2

    def test_no_dia_seguinte_coleta_de_novo(self, motor: Engine) -> None:
        _acompanhar(motor, CNPJ)
        coletar = ColetaFalsa(coleta(), coleta())
        _rodar(motor, coletar)

        _rodar(motor, coletar, agora=HOJE + timedelta(days=1))

        assert coletar.chamadas == 2
        assert len(_observacoes(motor, CNPJ)) == 3

    def test_sem_empresas_acompanhadas_nao_chama_a_rede(self, motor: Engine) -> None:
        coletar = ColetaFalsa()

        resumo = _rodar(motor, coletar)

        assert coletar.chamadas == 0
        assert resumo == Resumo(coletadas=[], puladas=[], falhas=[])


class TestFalhas:
    def test_falha_de_uma_empresa_nao_para_as_outras(self, motor: Engine) -> None:
        _acompanhar(motor, CNPJ)
        _acompanhar(motor, OUTRO)
        coletar = ColetaFalsa(TodasAsFontesFalharam([ERRO]), coleta())

        resumo = _rodar(motor, coletar)

        assert resumo == Resumo(coletadas=[OUTRO], puladas=[], falhas=[CNPJ])
        assert len(_observacoes(motor, CNPJ)) == 1
        assert len(_observacoes(motor, OUTRO)) == 2

    def test_cnpj_que_sumiu_da_base_conta_como_falha(self, motor: Engine) -> None:
        _acompanhar(motor, CNPJ)

        resumo = _rodar(motor, ColetaFalsa(CnpjNaoEncontrado(CNPJ)))

        assert resumo.falhas == [CNPJ]

    def test_empresa_que_falhou_e_tentada_de_novo_no_mesmo_dia(self, motor: Engine) -> None:
        # Só a coleta que deu certo conta como "coletada hoje".
        _acompanhar(motor, CNPJ)
        coletar = ColetaFalsa(TodasAsFontesFalharam([ERRO]), coleta())
        _rodar(motor, coletar)

        segunda = _rodar(motor, coletar, agora=HOJE + timedelta(hours=1))

        assert segunda.coletadas == [CNPJ]


class TestMain:
    @pytest.fixture
    def banco(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
        url = f"sqlite:///{(tmp_path / 'coleta.db').as_posix()}"
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("BRASILAPI_BASE_URL", "https://primaria.exemplo/api")
        monkeypatch.setenv("MINHARECEITA_BASE_URL", "https://reserva.exemplo")
        motor = criar_motor(url)
        _acompanhar(motor, CNPJ, coletado_em="2020-01-01 10:00:00")
        motor.dispose()
        return url

    def test_tudo_certo_sai_com_zero(
        self, banco: str, exemplo_brasilapi: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        rede = httpx.MockTransport(lambda _pedido: httpx.Response(200, json=exemplo_brasilapi))

        codigo = main(transporte=rede)

        assert codigo == 0
        assert "1 coletada" in capsys.readouterr().out

    def test_falha_sai_com_um_para_o_actions_marcar_vermelho(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 403 não é repetido, então o teste não precisa dormir
        codigo = main(transporte=httpx.MockTransport(lambda _pedido: httpx.Response(403)))

        assert codigo == 1
        assert "1 falha" in capsys.readouterr().out
