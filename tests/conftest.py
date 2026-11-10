"""Fixtures compartilhadas entre testes.

Carrega fixtures persistidas em `dados/` uma única vez por sessão. Se um
fixture for removido, o teste falha na hora com FileNotFoundError, em vez
de silenciosamente servir dados errados.

Os testes de banco rodam em SQLite e em PostgreSQL. O PostgreSQL só entra
com `TEST_DATABASE_URL` definida (no CI, um serviço do workflow); sem ela,
esses casos são pulados e `pytest` continua passando sem conexão.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine

from src.db import criar_motor

_ROOT = Path(__file__).resolve().parent.parent
_DADOS = _ROOT / "dados"
_URL_POSTGRES = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "postgresql"])
def url_banco(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    """URL de um banco vazio, uma vez em cada banco suportado."""
    if request.param == "sqlite":
        return f"sqlite:///{(tmp_path / 'teste.db').as_posix()}"
    if not _URL_POSTGRES:
        # No CI, pular em silêncio deixaria o PostgreSQL sem teste com o check verde.
        if os.environ.get("CI"):
            pytest.fail("no CI, TEST_DATABASE_URL é obrigatória")
        pytest.skip("defina TEST_DATABASE_URL para testar também no PostgreSQL")
    _apagar_tabelas(_URL_POSTGRES)
    return _URL_POSTGRES


@pytest.fixture
def motor(url_banco: str) -> Iterator[Engine]:
    """Banco vazio com o schema aplicado."""
    motor = criar_motor(url_banco)
    yield motor
    motor.dispose()


def _apagar_tabelas(url: str) -> None:
    # O PostgreSQL de teste é compartilhado entre os testes: cada um começa do zero.
    motor = create_engine(url)
    with motor.begin() as con:
        con.exec_driver_sql("DROP TABLE IF EXISTS observacao, falha_coleta, empresa CASCADE")
    motor.dispose()


def _carregar(nome_do_arquivo: str) -> dict[str, Any]:
    caminho = _DADOS / nome_do_arquivo
    return json.loads(caminho.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def exemplo_brasilapi() -> dict[str, Any]:
    """Resposta real da BrasilAPI para o CNPJ 11.222.333/0001-81.

    Único ajuste: nome e CPF parcial de quem consta em `qsa` foram omitidos,
    porque o repositório é público e nenhum teste depende desses valores.
    """
    return _carregar("exemplo_brasilapi.json")


@pytest.fixture(scope="session")
def exemplo_minhareceita() -> dict[str, Any]:
    """Resposta real da Minha Receita para o mesmo CNPJ, com o mesmo ajuste."""
    return _carregar("exemplo_minhareceita.json")
