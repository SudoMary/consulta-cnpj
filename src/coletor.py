"""Recoleta diária das empresas acompanhadas: `python -m src.coletor`.

Roda no GitHub Actions (`.github/workflows/coleta.yml`), fora da hospedagem,
que dorme quando ninguém acessa, e grava direto no banco de produção.

Idempotente por dia: empresa que já tem observação de hoje (UTC) é pulada, então
rodar duas vezes no mesmo dia não duplica nada. O cache de 24 horas não serve
para isso: uma coleta feita às 9h de ontem ainda estaria "no cache" às 8h de
hoje, e o dia ficaria sem observação.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial

import httpx
from sqlalchemy import Engine

from . import repo
from .cliente import CnpjNaoEncontrado, Coleta, TodasAsFontesFalharam, consultar_externo
from .config import Settings
from .db import criar_motor
from .servico import ORIGEM_CACHE_VENCIDO, consultar
from .validacao import formata_cnpj


@dataclass
class Resumo:
    """O que aconteceu com cada empresa acompanhada nesta execução."""

    coletadas: list[str] = field(default_factory=list)
    puladas: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)


def coletar_acompanhadas(
    *,
    motor: Engine,
    coletar: Callable[[str], Coleta],
    ttl_horas: int,
    agora: datetime | None = None,
) -> Resumo:
    """Coleta cada empresa acompanhada que ainda não foi coletada hoje.

    A falha de uma empresa não interrompe as outras. As falhas de fonte ficam
    registradas em `falha_coleta` pelo serviço.
    """
    agora = agora or datetime.now(UTC)
    hoje = agora.astimezone(UTC).strftime("%Y-%m-%d")
    with motor.connect() as con:
        cnpjs = repo.cnpjs_acompanhados(con)

    resumo = Resumo()
    for cnpj in cnpjs:
        with motor.connect() as con:
            recente = repo.observacao_mais_nova(con, cnpj)
        if recente is not None and recente["coletado_em"].startswith(hoje):
            resumo.puladas.append(cnpj)
            continue

        try:
            consulta = consultar(
                cnpj, motor=motor, coletar=coletar, ttl_horas=ttl_horas, forcar=True, agora=agora
            )
        except (CnpjNaoEncontrado, TodasAsFontesFalharam):
            resumo.falhas.append(cnpj)
            continue

        # Com as fontes fora, o serviço devolve o dado antigo: para a tela
        # serve, mas para a coleta do dia é falha.
        if consulta.origem == ORIGEM_CACHE_VENCIDO:
            resumo.falhas.append(cnpj)
        else:
            resumo.coletadas.append(cnpj)
    return resumo


def formatar_resumo(resumo: Resumo) -> str:
    """Uma linha por empresa e o total, para o log do Actions."""
    linhas = [f"  {formata_cnpj(cnpj)}  coletada" for cnpj in resumo.coletadas]
    linhas += [f"  {formata_cnpj(cnpj)}  já coletada hoje" for cnpj in resumo.puladas]
    linhas += [f"  {formata_cnpj(cnpj)}  FALHOU (ver falha_coleta)" for cnpj in resumo.falhas]
    if not linhas:
        return "Nenhuma empresa acompanhada."
    total = (
        f"Total: {len(resumo.coletadas)} coletada(s), "
        f"{len(resumo.puladas)} já coletada(s) hoje, {len(resumo.falhas)} falha(s)."
    )
    return "\n".join([*linhas, total])


def main(*, transporte: httpx.BaseTransport | None = None) -> int:
    """Roda a coleta e devolve 1 se alguma empresa falhou.

    O código 1 deixa a execução vermelha na aba Actions, para a falha não
    passar despercebida. `transporte` existe para os testes trocarem a rede.
    """
    config = Settings()
    motor = criar_motor(config.url_banco)
    try:
        with httpx.Client(transport=transporte) as http:
            resumo = coletar_acompanhadas(
                motor=motor,
                coletar=partial(consultar_externo, http=http, config=config),
                ttl_horas=config.cache_ttl_horas,
            )
    finally:
        motor.dispose()
    print(formatar_resumo(resumo))
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
