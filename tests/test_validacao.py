"""Testes da validação de CNPJ.

CNPJ tem 14 dígitos; os dois últimos são dígitos verificadores calculados
a partir dos 12 primeiros. Um CNPJ válido passa na conta; qualquer erro de
digitação derruba a conta.

CNPJ de referência: 11.222.333/0001-81 (sem máscara: 11222333000181).
"""

from __future__ import annotations

from validacao import cnpj_valido, so_digitos

CNPJ_VALIDO = "11222333000181"
CNPJ_VALIDO_COM_MASCARA = "11.222.333/0001-81"


class TestSoDigitos:
    def test_remove_mascara(self) -> None:
        # Arrange
        texto = CNPJ_VALIDO_COM_MASCARA

        # Act
        resultado = so_digitos(texto)

        # Assert
        assert resultado == CNPJ_VALIDO

    def test_texto_so_com_digitos_nao_muda(self) -> None:
        # Arrange
        texto = CNPJ_VALIDO

        # Act
        resultado = so_digitos(texto)

        # Assert
        assert resultado == CNPJ_VALIDO

    def test_string_vazia_devolve_string_vazia(self) -> None:
        # Arrange
        texto = ""

        # Act
        resultado = so_digitos(texto)

        # Assert
        assert resultado == ""


class TestCnpjValido:
    def test_cnpj_valido_sem_mascara(self) -> None:
        # Arrange
        cnpj = CNPJ_VALIDO

        # Act
        resultado = cnpj_valido(cnpj)

        # Assert
        assert resultado is True

    def test_cnpj_valido_com_mascara(self) -> None:
        # Arrange
        cnpj = CNPJ_VALIDO_COM_MASCARA

        # Act
        resultado = cnpj_valido(cnpj)

        # Assert
        assert resultado is True

    def test_ultimo_digito_verificador_trocado_e_recusado(self) -> None:
        # o correto termina em 1; trocando por 2 a conta nao fecha
        assert cnpj_valido("11222333000182") is False

    def test_primeiro_digito_verificador_trocado_e_recusado(self) -> None:
        # o correto e ...0018-1; trocando o 8 do meio
        assert cnpj_valido("11222333000191") is False

    def test_14_digitos_zero_e_recusado(self) -> None:
        # todos os digitos iguais passam na conta, mas nao existem
        assert cnpj_valido("00000000000000") is False

    def test_14_digitos_um_e_recusado(self) -> None:
        assert cnpj_valido("11111111111111") is False

    def test_tamanho_menor_que_14_e_recusado(self) -> None:
        assert cnpj_valido("1122233300") is False

    def test_tamanho_maior_que_14_e_recusado(self) -> None:
        assert cnpj_valido("112223330001811") is False

    def test_string_vazia_e_recusada(self) -> None:
        assert cnpj_valido("") is False

    def test_none_e_recusado(self) -> None:
        # type: ignore[arg-type]
        assert cnpj_valido(None) is False
