"""Fixtures compartilhadas entre testes.

Carrega fixtures persistidas em `dados/` uma única vez por sessão. Se um
fixture for removido, o teste falha na hora com FileNotFoundError, em vez
de silenciosamente servir dados errados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DADOS = _ROOT / "dados"


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
