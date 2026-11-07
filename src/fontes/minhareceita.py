"""Adapter da Minha Receita (fonte de reserva).

Mesmo contrato da BrasilAPI: `buscar` devolve a resposta HTTP sem interpretar
o status, e `normalizar` é a tradução comum de `fontes/base.py`. O que muda de
uma fonte para a outra é o caminho da URL.
"""

from __future__ import annotations

import httpx

from . import base

# Valor gravado em `observacao.fonte`; precisa constar no CHECK do schema.
NOME = "minhareceita"

normalizar = base.normalizar


def buscar(cnpj: str, *, cliente: httpx.Client, base_url: str, timeout: float) -> httpx.Response:
    """Consulta o CNPJ na Minha Receita e devolve a resposta HTTP sem interpretá-la.

    Timeout e erro de rede (`httpx.HTTPError`) sobem para quem chamou.
    """
    return cliente.get(f"{base_url.rstrip('/')}/{cnpj}", timeout=timeout)
