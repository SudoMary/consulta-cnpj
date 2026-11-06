"""Conexão com SQLite e aplicação do schema.

Este módulo é a única porta de entrada para o banco. Abre a conexão, liga
as pragmas que o SQLite desativa por padrão e aplica o schema (idempotente).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Localiza `schema.sql` na raiz do projeto, independente do cwd em que o
# processo foi iniciado.
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def conectar(caminho: str = ":memory:") -> sqlite3.Connection:
    """Abre conexão SQLite com foreign keys ligadas e schema aplicado.

    Aceita ``:memory:`` (testes) ou caminho de arquivo (runtime).
    Idempotente: chamar duas vezes no mesmo arquivo não quebra, porque o
    schema usa ``CREATE TABLE IF NOT EXISTS``.

    O chamador é responsável por fechar a conexão (``con.close()``).
    """
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    # O SQLite ignora FKs por padrão; sem esta linha, REFERENCES é decoração.
    con.execute("PRAGMA foreign_keys = ON")
    # UTF-8 explícito: o schema tem comentários acentuados e o default no
    # Windows é cp1252.
    con.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return con
