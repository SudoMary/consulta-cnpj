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


@pytest.fixture(scope="session")
def exemplo_brasilapi() -> dict[str, Any]:
    """Resposta real da BrasilAPI para o CNPJ 11.222.333/0001-81.

    Único ajuste: nome e CPF parcial de quem consta em `qsa` foram omitidos,
    porque o repositório é público e nenhum teste depende desses valores.
    """
    caminho = _DADOS / "exemplo_brasilapi.json"
    return json.loads(caminho.read_text(encoding="utf-8"))
