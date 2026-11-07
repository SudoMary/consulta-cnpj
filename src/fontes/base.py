"""O formato normalizado, comum às fontes.

BrasilAPI e Minha Receita publicam os dados da Receita no mesmo formato: as
respostas reais comparadas em 2026-11-06 têm chaves idênticas. Por isso a
tradução para as colunas de `observacao` mora aqui, em um lugar só. Se uma
fonte divergir, ela passa a ter o próprio `normalizar`, e as outras não mudam.

Nomes de campo abaixo foram VERIFICADOS contra respostas reais. Não são chute
de IA. Ver `dados/exemplo_brasilapi.json` e `dados/exemplo_minhareceita.json`.
"""

from __future__ import annotations

from typing import Any


def normalizar(json_bruto: dict[str, Any]) -> dict[str, Any]:
    """Traduz a resposta de uma fonte para o formato interno do schema.

    Função pura, sem rede. O schema `observacao` tem 11 colunas de dados. As
    fontes devolvem dezenas de campos, alguns com nomes diferentes dos do schema:

    - `descricao_situacao_cadastral` (texto "ATIVA") → `situacao`
    - `data_situacao_cadastral` → `data_situacao`
    - `cnae_fiscal` (int) → `cnae_codigo` (TEXT com 7 dígitos)
    - `cnae_fiscal_descricao` → `cnae_descricao`
    - `capital_social` (número em reais) → `capital_centavos` (int)
    - `qsa` (lista de sócios) → `qtd_socios` (int)

    O JSON bruto inteiro deve ser salvo em `bruto_json` pelo chamador —
    este normalizar descarta o que o schema não tem coluna para guardar.
    Campos ausentes no `json_bruto` viram ``None`` em vez de estourar
    ``KeyError``. O `nome_fantasia` vazio também: as fontes devolvem ``""``
    para empresa sem nome fantasia, e o schema reserva ``NULL`` para "não
    informado".
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

    As fontes entregam int, então o zero à esquerda já chega perdido: a SLC
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
