"""Validação de CNPJ.

CNPJ tem 14 dígitos; os 2 últimos são dígitos verificadores calculados a
partir dos 12 primeiros. Se a conta não fecha, o número foi digitado errado
(não é o caso de "empresa não existe" — esse é outro problema).
"""

from __future__ import annotations

PESOS_DV1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
PESOS_DV2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def so_digitos(texto: str) -> str:
    """Devolve apenas os dígitos do texto, sem máscara."""
    return "".join(c for c in texto if c.isdigit())


def _digito_verificador(digitos: str, pesos: tuple[int, ...]) -> str:
    soma = sum(int(d) * p for d, p in zip(digitos, pesos, strict=True))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(texto: str | None) -> bool:
    """Devolve True se o texto representa um CNPJ válido.

    Aceita com ou sem máscara. Rejeita None, vazio, tamanho diferente de 14
    dígitos, todos os dígitos iguais e qualquer erro nos dígitos verificadores.
    """
    if texto is None or not isinstance(texto, str):
        return False

    digitos = so_digitos(texto)
    if len(digitos) != 14:
        return False

    # CNPJ com todos os dígitos iguais passa na conta do DV, mas não existe.
    if len(set(digitos)) == 1:
        return False

    dv1 = _digito_verificador(digitos[:12], PESOS_DV1)
    if dv1 != digitos[12]:
        return False

    dv2 = _digito_verificador(digitos[:13], PESOS_DV2)
    return dv2 == digitos[13]
