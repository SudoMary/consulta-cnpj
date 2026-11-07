"""Adapter da BrasilAPI (fonte primária).

Duas responsabilidades, separadas de propósito:

- `buscar(...) -> httpx.Response`: faz o GET e devolve a resposta como veio.
  Não interpreta o status: 404, 429 e 5xx pedem reações diferentes, e quem
  decide é o `cliente.py`. Recebe cliente HTTP, URL base e timeout de quem
  chama, para testar sem rede e sem depender de `.env`.
- `normalizar(json_bruto) -> dict`: pura, sem rede. Traduz o formato da
  API para o formato interno (nomes do schema `observacao`). Testável com
  o fixture real em `dados/exemplo_brasilapi.json`.

Nomes de campo abaixo foram VERIFICADOS contra resposta real da BrasilAPI
(2026-11-06). Não são chute de IA. Ver `dados/exemplo_brasilapi.json`.
"""

from __future__ import annotations

from typing import Any

import httpx

# Valor gravado em `observacao.fonte`; precisa constar no CHECK do schema.
NOME = "brasilapi"


def buscar(cnpj: str, *, cliente: httpx.Client, base_url: str, timeout: float) -> httpx.Response:
    """Consulta o CNPJ na BrasilAPI e devolve a resposta HTTP sem interpretá-la.

    Timeout e erro de rede (`httpx.HTTPError`) sobem para quem chamou.
    """
    return cliente.get(f"{base_url.rstrip('/')}/cnpj/v1/{cnpj}", timeout=timeout)


def normalizar(json_bruto: dict[str, Any]) -> dict[str, Any]:
    """Traduz a resposta da BrasilAPI para o formato interno do schema.

    O schema `observacao` tem 11 colunas de dados. A BrasilAPI devolve
    dezenas de campos — alguns com nomes diferentes dos do schema:

    - `descricao_situacao_cadastral` (texto "ATIVA") → `situacao`
    - `data_situacao_cadastral` → `data_situacao`
    - `cnae_fiscal` (int) → `cnae_codigo` (TEXT com 7 dígitos)
    - `cnae_fiscal_descricao` → `cnae_descricao`
    - `capital_social` (float em reais) → `capital_centavos` (int)
    - `qsa` (lista de sócios) → `qtd_socios` (int)

    O JSON bruto inteiro deve ser salvo em `bruto_json` pelo chamador —
    este normalizar descarta o que o schema não tem coluna para guardar.
    Campos ausentes no `json_bruto` viram ``None`` em vez de estourar
    ``KeyError``. O `nome_fantasia` vazio também: a API devolve ``""`` para
    empresa sem nome fantasia, e o schema reserva ``NULL`` para "não informado".
    """
    return {
        "razao_social": json_bruto.get("razao_social"),
        "nome_fantasia": json_bruto.get("nome_fantasia") or None,
        "situacao": json_bruto.get("descricao_situacao_cadastral"),
        "data_situacao": json_bruto.get("data_situacao_cadastral"),
        "porte": json_bruto.get("porte"),
        "cnae_codigo": _cnae_para_texto(json_bruto.get("cnae_fiscal")),
        "cnae_descricao": json_bruto.get("cnae_fiscal_descricao"),
        "municipio": json_bruto.get("municipio"),
        "uf": json_bruto.get("uf"),
        "capital_centavos": _para_centavos(json_bruto.get("capital_social")),
        "qtd_socios": _qtd_socios(json_bruto.get("qsa")),
    }


def _cnae_para_texto(valor: Any) -> str | None:
    """Devolve o CNAE como texto de 7 dígitos, preservando ``None``.

    A API entrega int, então o zero à esquerda já chega perdido: a SLC
    Agrícola vem como 161099, e o código real é 0161099. ``zfill`` o restaura.
    """
    if valor is None:
        return None
    return str(valor).zfill(7)


def _para_centavos(valor_em_reais: Any) -> int | None:
    """Converte reais (float) para centavos (int).

    Usa ``round``, não ``int``: ``int(1.15 * 100)`` trunca para 114 por
    causa do erro de ponto flutuante; ``round(1.15 * 100)`` devolve 115.
    Dinheiro nunca é guardado em float — este é o único ponto em que ele
    toca o código, e sai daqui como int.
    """
    if valor_em_reais is None:
        return None
    return round(float(valor_em_reais) * 100)


def _qtd_socios(qsa: Any) -> int | None:
    """Extrai a quantidade de sócios de `qsa` (lista).

    ``qsa`` na API é a lista completa de sócios; o schema só precisa da
    quantidade. ``None`` vira ``None`` (campo opcional no schema). Lista
    vazia vira 0 (empresa sem sócios é válida — MEI, por exemplo).
    """
    if qsa is None:
        return None
    return len(qsa)
