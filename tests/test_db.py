"""Testes da camada de conexão com SQLite (src/db.py).

Todos usam `:memory:` quando possível, exceto o teste de idempotência de
schema, que precisa de arquivo em disco (`tmp_path`, fornecido pelo pytest).
"""

from __future__ import annotations

import sqlite3

import pytest

from src.db import conectar


class TestConectar:
    def test_aplica_schema_em_memoria(self) -> None:
        # Act
        con = conectar(":memory:")

        try:
            # Assert
            tabelas = {
                row["name"]
                for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert {"empresa", "observacao", "falha_coleta"} <= tabelas
        finally:
            con.close()

    def test_foreign_keys_ligadas(self) -> None:
        con = conectar(":memory:")

        try:
            assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            con.close()

    def test_row_factory_permite_acesso_por_nome(self) -> None:
        con = conectar(":memory:")

        try:
            con.execute(
                "INSERT INTO empresa (cnpj, primeira_consulta, ultima_consulta) VALUES (?, ?, ?)",
                ("11222333000181", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
            )
            row = con.execute(
                "SELECT cnpj FROM empresa WHERE cnpj = ?", ("11222333000181",)
            ).fetchone()

            assert row["cnpj"] == "11222333000181"
        finally:
            con.close()

    def test_conectar_duas_vezes_no_mesmo_arquivo_e_idempotente(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        # Arrange
        caminho = tmp_path / "teste.db"

        # Act: aplica o schema duas vezes no mesmo arquivo
        con1 = conectar(str(caminho))
        con1.close()
        con2 = conectar(str(caminho))

        try:
            # Assert: banco vazio (schema reaplicado sem erro)
            assert con2.execute("SELECT COUNT(*) FROM empresa").fetchone()[0] == 0
        finally:
            con2.close()


class TestRestricoes:
    def test_fk_violation_estoura_em_observacao_sem_empresa(self) -> None:
        con = conectar(":memory:")

        try:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO observacao (cnpj, coletado_em, fonte, bruto_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("11222333000181", "2026-01-01 00:00:00", "brasilapi", "{}"),
                )
        finally:
            con.close()

    def test_check_fonte_invalida_estoura(self) -> None:
        con = conectar(":memory:")

        try:
            con.execute(
                "INSERT INTO empresa (cnpj, primeira_consulta, ultima_consulta) VALUES (?, ?, ?)",
                ("11222333000181", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
            )

            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO observacao (cnpj, coletado_em, fonte, bruto_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("11222333000181", "2026-01-01 00:00:00", "outra", "{}"),
                )
        finally:
            con.close()

    def test_check_cnpj_tamanho_invalido_estoura(self) -> None:
        con = conectar(":memory:")

        try:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO empresa (cnpj, primeira_consulta, ultima_consulta) "
                    "VALUES (?, ?, ?)",
                    ("123", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
                )
        finally:
            con.close()
