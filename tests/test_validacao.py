"""Testes da validação e formatação de CNPJ.

CNPJ tem 14 dígitos; os dois últimos são dígitos verificadores calculados
a partir dos 12 primeiros. Um CNPJ válido passa na conta; qualquer erro de
digitação derruba a conta.

CNPJ de referência: 11.222.333/0001-81 (sem máscara: 11222333000181).
"""

from __future__ import annotations

from validacao import cnpj_valido, formata_cnpj, so_digitos

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

    def test_ignora_digito_que_nao_e_ascii(self) -> None:
        # "²" e U+0661 (1 arábico) passam em str.isdigit(), mas não são dígitos de CNPJ
        assert so_digitos("\u00b21\u06612") == "12"


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

    def test_expoente_e_recusado_sem_estourar(self) -> None:
        # "²" no lugar de um dígito derrubava o int() do cálculo com ValueError
        assert cnpj_valido("\u00b21222333000181") is False

    def test_digito_de_outro_alfabeto_e_recusado(self) -> None:
        # U+0661 é o 1 arábico: int() aceita, a conta fechava e o texto
        # não ASCII seguiria para a URL da API
        assert cnpj_valido("\u06611222333000181") is False


class TestFormataCnpj:
    def test_formata_sem_mascara(self) -> None:
        # Arrange
        cnpj = CNPJ_VALIDO

        # Act
        resultado = formata_cnpj(cnpj)

        # Assert
        assert resultado == CNPJ_VALIDO_COM_MASCARA

    def test_formata_com_mascara_e_idempotente(self) -> None:
        # Arrange
        cnpj = CNPJ_VALIDO_COM_MASCARA

        # Act
        resultado = formata_cnpj(cnpj)

        # Assert
        assert resultado == CNPJ_VALIDO_COM_MASCARA

    def test_14_digitos_invalidos_ainda_formatam(self) -> None:
        # formata_cnpj NAO valida DV; formata qualquer sequencia de 14 digitos
        assert formata_cnpj("00000000000000") == "00.000.000/0000-00"

    def test_texto_com_menos_de_14_digitos_devolve_entrada(self) -> None:
        assert formata_cnpj("1122233300") == "1122233300"

    def test_string_vazia_devolve_string_vazia(self) -> None:
        assert formata_cnpj("") == ""

    def test_none_devolve_none(self) -> None:
        # type: ignore[arg-type]
        assert formata_cnpj(None) is None
