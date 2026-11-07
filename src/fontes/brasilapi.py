"""Adapter da BrasilAPI (fonte primária).

- `buscar(...) -> httpx.Response`: faz o GET e devolve a resposta como veio.
  Não interpreta o status: 404, 429 e 5xx pedem reações diferentes, e quem
  decide é o `cliente.py`. Recebe cliente HTTP, URL base e timeout de quem
  chama, para testar sem rede e sem depender de `.env`.
- `normalizar(json_bruto) -> dict`: a tradução comum, de `fontes/base.py`.
"""

from __future__ import annotations

import httpx

from . import base

# Valor gravado em `observacao.fonte`; precisa constar no CHECK do schema.
NOME = "brasilapi"

normalizar = base.normalizar


def buscar(cnpj: str, *, cliente: httpx.Client, base_url: str, timeout: float) -> httpx.Response:
    """Consulta o CNPJ na BrasilAPI e devolve a resposta HTTP sem interpretá-la.

    Timeout e erro de rede (`httpx.HTTPError`) sobem para quem chamou.
    """
    return cliente.get(f"{base_url.rstrip('/')}/cnpj/v1/{cnpj}", timeout=timeout)
