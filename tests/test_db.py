"""Testes da conexão e do schema (src/db.py).

Rodam no SQLite e, com `TEST_DATABASE_URL` definida, também no PostgreSQL:
o mesmo schema e as mesmas restrições precisam valer nos dois bancos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from src.db import criar_motor

CNPJ = "11222333000181"
QUANDO = "2026-01-01 00:00:00"


def _inserir_empresa(con: Connection, cnpj: str = CNPJ) -> None:
    con.execute(
        text(
            "INSERT INTO empresa (cnpj, primeira_consulta, ultima_consulta) "
            "VALUES (:cnpj, :quando, :quando)"
        ),
        {"cnpj": cnpj, "quando": QUANDO},
    )


def _inserir_observacao(con: Connection, **campos: Any) -> None:
    valores = {"cnpj": CNPJ, "coletado_em": QUANDO, "fonte": "brasilapi", "bruto_json": "{}"}
    valores.update(campos)
    colunas = ", ".join(valores)
    marcadores = ", ".join(f":{coluna}" for coluna in valores)
    con.execute(text(f"INSERT INTO observacao ({colunas}) VALUES ({marcadores})"), valores)


class TestCriarMotor:
    def test_aplica_o_schema(self, motor: Engine) -> None:
        tabelas = set(inspect(motor).get_table_names())

        assert {"empresa", "observacao", "falha_coleta"} <= tabelas

    def test_aplicar_duas_vezes_e_idempotente(self, url_banco: str) -> None:
        # Act: aplica o schema duas vezes no mesmo banco
        criar_motor(url_banco).dispose()
        motor = criar_motor(url_banco)

        # Assert: banco vazio, schema reaplicado sem erro
        try:
            with motor.connect() as con:
                assert con.execute(text("SELECT COUNT(*) FROM empresa")).scalar_one() == 0
        finally:
            motor.dispose()

    def test_id_e_gerado_pelo_banco(self, motor: Engine) -> None:
        with motor.begin() as con:
            _inserir_empresa(con)
            _inserir_observacao(con)
            _inserir_observacao(con)
            ids = con.execute(text("SELECT id FROM observacao ORDER BY id")).scalars().all()

        assert len(set(ids)) == 2
        assert all(ids)

    def test_sqlite_liga_as_chaves_estrangeiras(self, tmp_path: Path) -> None:
        # O SQLite ignora FK por padrão; o PostgreSQL já as respeita.
        motor = criar_motor(f"sqlite:///{(tmp_path / 'fk.db').as_posix()}")
        try:
            with motor.connect() as con:
                assert con.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        finally:
            motor.dispose()


class TestRestricoes:
    def test_observacao_sem_empresa_e_recusada(self, motor: Engine) -> None:
        with pytest.raises(IntegrityError), motor.begin() as con:
            _inserir_observacao(con)

    def test_fonte_fora_da_lista_e_recusada(self, motor: Engine) -> None:
        with motor.begin() as con:
            _inserir_empresa(con)

        with pytest.raises(IntegrityError), motor.begin() as con:
            _inserir_observacao(con, fonte="outra")

    def test_cnpj_com_tamanho_errado_e_recusado(self, motor: Engine) -> None:
        with pytest.raises(IntegrityError), motor.begin() as con:
            _inserir_empresa(con, cnpj="123")

    def test_capital_da_petrobras_cabe_na_coluna(self, motor: Engine) -> None:
        # R$ 205.431.960.000,00 são 20.543.196.000.000 centavos: não cabe no
        # INTEGER de 32 bits do PostgreSQL, por isso a coluna é BIGINT.
        centavos = 20_543_196_000_000
        with motor.begin() as con:
            _inserir_empresa(con)
            _inserir_observacao(con, capital_centavos=centavos)
            gravado = con.execute(text("SELECT capital_centavos FROM observacao")).scalar_one()

        assert gravado == centavos
