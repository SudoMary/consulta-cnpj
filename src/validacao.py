"""Validação e formatação de CNPJ.

CNPJ tem 14 dígitos; os 2 últimos são dígitos verificadores calculados a
partir dos 12 primeiros. Se a conta não fecha, o número foi digitado errado
(não é o caso de "empresa não existe" — esse é outro problema).
"""

from __future__ import annotations

PESOS_DV1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
PESOS_DV2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def so_digitos(texto: str) -> str:
    """Devolve apenas os dígitos de 0 a 9 do texto, sem máscara."""
    # Não usa `str.isdigit()`: ele aceita "²", que derruba o `int()` do cálculo
    # do DV, e dígitos de outros alfabetos, que seguiriam para a URL da API.
    return "".join(c for c in texto if c in "0123456789")


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


def formata_cnpj(texto: str | None) -> str | None:
    """Formata um CNPJ para o padrão XX.XXX.XXX/XXXX-XX.

    Não valida os dígitos verificadores — formatação e validação são coisas
    diferentes. Aceita com ou sem máscara e é idempotente.

    Retorna a entrada inalterada quando não é possível formatar (vazio, None,
    ou texto sem exatamente 14 dígitos). Devolver o valor cru é melhor que
    quebrar a exibição: o chamador decide se aquilo é erro.
    """
    if texto is None:
        return None

    digitos = so_digitos(texto)
    if len(digitos) != 14:
        return texto

    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
