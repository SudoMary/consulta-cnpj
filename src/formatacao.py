"""Dado virando texto: a linha de comando e a tela usam as mesmas frases.

Quem calcula devolve dado; aqui só se formata. Nenhuma regra de negócio.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .servico import ORIGEM_CACHE, ORIGEM_CACHE_VENCIDO, Consulta
from .validacao import formata_cnpj

NAO_INFORMADO = "não informado"
MENSAGEM_NAO_ENCONTRADO = "CNPJ não encontrado na base da Receita."
MENSAGEM_SEM_FONTES = (
    "As fontes estão fora do ar e não há consulta anterior deste CNPJ. Tente de novo mais tarde."
)

NOMES_DAS_FONTES = {"brasilapi": "BrasilAPI", "minhareceita": "Minha Receita"}

# Nome legível de cada campo, na ordem em que aparece na ficha.
ROTULOS = {
    "razao_social": "Razão social",
    "nome_fantasia": "Nome fantasia",
    "situacao": "Situação",
    "data_situacao": "Desde",
    "porte": "Porte",
    "cnae_codigo": "CNAE",
    "cnae_descricao": "Atividade",
    "municipio": "Município",
    "uf": "UF",
    "capital_centavos": "Capital social",
    "qtd_socios": "Sócios",
}

# Gravidade de cada situação cadastral, para cor e ícone na tela.
_GRAVIDADE = {
    "ATIVA": "ok",
    "SUSPENSA": "alerta",
    "INAPTA": "grave",
    "BAIXADA": "grave",
    "NULA": "grave",
}

# O banco guarda UTC; a tela mostra Brasília, que não tem horário de verão
# desde 2019. Fuso fixo evita depender da base de fusos do sistema.
_BRASILIA = timedelta(hours=-3)
_FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"


def campos_da_ficha(observacao: dict[str, Any]) -> list[tuple[str, str]]:
    """Rótulo e valor de cada campo da ficha, já formatados, em ordem."""
    campos = [("CNPJ", formata_cnpj(observacao["cnpj"]) or NAO_INFORMADO)]
    for campo, rotulo in ROTULOS.items():
        valor = observacao[campo]
        if campo == "capital_centavos":
            texto = formatar_capital(valor)
        elif campo == "cnae_codigo":
            texto = formatar_cnae(valor)
        elif campo == "data_situacao":
            texto = data_br(valor)
        else:
            texto = ou_nao_informado(valor)
        campos.append((rotulo, texto))
    return campos


def formatar_capital(centavos: int | None) -> str:
    """Formata centavos como reais, sem passar por float."""
    if centavos is None:
        return NAO_INFORMADO
    reais, resto = divmod(centavos, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{resto:02d}"


def formatar_cnae(codigo: str | None) -> str:
    """CNAE no formato do comprovante da Receita: 8550301 vira 85.50-3-01."""
    if not codigo or len(codigo) != 7 or not codigo.isdigit():
        return ou_nao_informado(codigo)
    return f"{codigo[:2]}.{codigo[2:4]}-{codigo[4]}-{codigo[5:]}"


def descrever_origem(consulta: Consulta) -> str:
    """Diz de onde veio o dado, em frase para o usuário."""
    idade = _idade_por_extenso(consulta.idade_horas)
    if consulta.origem == ORIGEM_CACHE:
        return f"do cache, há {idade}"
    if consulta.origem == ORIGEM_CACHE_VENCIDO:
        return f"consultado há {idade}, as fontes estão fora do ar agora"
    return f"consultado agora na {NOMES_DAS_FONTES.get(consulta.origem, consulta.origem)}"


def gravidade_da_situacao(situacao: str | None) -> str:
    """'ok', 'alerta', 'grave' ou 'neutro', para a tela escolher cor e ícone."""
    if not situacao:
        return "neutro"
    return _GRAVIDADE.get(situacao, "alerta")


def data_br(data_iso: str | None) -> str:
    """'2009-09-02' vira '02/09/2009'."""
    try:
        return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ou_nao_informado(data_iso)


def data_hora_br(momento_utc: str) -> str:
    """Momento gravado em UTC, mostrado no horário de Brasília."""
    momento = datetime.strptime(momento_utc, _FORMATO_BANCO) + _BRASILIA
    return momento.strftime("%d/%m/%Y, %H:%M")


def ou_nao_informado(valor: Any) -> str:
    """O valor como texto, ou "não informado" quando a fonte não trouxe."""
    return NAO_INFORMADO if valor is None else str(valor)


def _idade_por_extenso(horas: float) -> str:
    if horas < 1:
        return "menos de 1 hora"
    if horas < 2:
        return "1 hora"
    if horas < 48:
        return f"{int(horas)} horas"
    return f"{int(horas // 24)} dias"
