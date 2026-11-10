"""Testes das regras do serviço: cache, degradação e detecção de mudança.

`coletar` é falso: conta as chamadas e segue um roteiro, então cada teste prova
quantas vezes a rede teria sido usada, sem tocar nela. O banco roda no SQLite
e, com `TEST_DATABASE_URL` definida, também no PostgreSQL. O relógio é passado
como argumento.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from src.cliente import CnpjNaoEncontrado, Coleta, ErroDeFonte, TodasAsFontesFalharam
from src.db import criar_motor
from src.repo import (
    empresa_por_cnpj,
    inserir_empresa_se_nao_existe,
    inserir_observacao,
    observacoes_por_cnpj,
)
from src.servico import (
    ORIGEM_CACHE,
    ORIGEM_CACHE_VENCIDO,
    Consulta,
    RegraDeNegocio,
    consultar,
    mudancas,
)

CNPJ = "11222333000181"
TTL_HORAS = 24
AGORA = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
AGORA_TEXTO = "2026-11-06 12:00:00"
ERRO_500 = ErroDeFonte("brasilapi", "HTTP 500")


class ColetaFalsa:
    """Faz o papel de `consultar_externo`: conta as chamadas e segue um roteiro.

    Uma chamada além do roteiro estoura `IndexError` e reprova o teste.
    """

    def __init__(self, *passos: Coleta | Exception) -> None:
        self.passos = list(passos)
        self.chamadas = 0

    def __call__(self, cnpj: str) -> Coleta:
        self.chamadas += 1
        passo = self.passos.pop(0)
        if isinstance(passo, Exception):
            raise passo
        return passo


def _coleta(
    situacao: str = "ATIVA",
    *,
    fonte: str = "brasilapi",
    erros: tuple[ErroDeFonte, ...] = (),
) -> Coleta:
    dados = {"razao_social": "ACME LTDA", "situacao": situacao}
    return Coleta(dados=dados, fonte=fonte, bruto_json='{"bruto": true}', erros=erros)


def _consultar(
    motor: Engine,
    coletar: ColetaFalsa,
    *,
    agora: datetime = AGORA,
    forcar: bool = False,
    cnpj: str = CNPJ,
) -> Consulta:
    return consultar(
        cnpj, motor=motor, coletar=coletar, ttl_horas=TTL_HORAS, forcar=forcar, agora=agora
    )


def _falhas(motor: Engine) -> list[tuple[Any, ...]]:
    with motor.connect() as con:
        linhas = con.execute(
            text("SELECT cnpj, ocorrido_em, fonte, motivo FROM falha_coleta ORDER BY id")
        ).all()
    return [tuple(linha) for linha in linhas]


def _observacoes(motor: Engine) -> list[dict[str, Any]]:
    with motor.connect() as con:
        return observacoes_por_cnpj(con, CNPJ)


def _empresa(motor: Engine) -> dict[str, Any] | None:
    with motor.connect() as con:
        return empresa_por_cnpj(con, CNPJ)


def _gravar_observacao(
    motor: Engine, quando: str, *, fonte: str = "brasilapi", **dados: Any
) -> None:
    with motor.begin() as con:
        inserir_empresa_se_nao_existe(con, CNPJ, quando)
        inserir_observacao(
            con, cnpj=CNPJ, dados=dados, fonte=fonte, coletado_em=quando, bruto_json="{}"
        )


class TestValidacaoAntesDaRede:
    @pytest.mark.parametrize("cnpj", ["11222333000182", "123", "", "00000000000000"])
    def test_cnpj_invalido_nao_chama_a_rede(self, motor: Engine, cnpj: str) -> None:
        coletar = ColetaFalsa()

        with pytest.raises(RegraDeNegocio, match="CNPJ inválido"):
            _consultar(motor, coletar, cnpj=cnpj)

        assert coletar.chamadas == 0

    def test_aceita_cnpj_com_mascara(self, motor: Engine) -> None:
        consulta = _consultar(motor, ColetaFalsa(_coleta()), cnpj="11.222.333/0001-81")

        assert consulta.observacao["cnpj"] == CNPJ


class TestPrimeiraConsulta:
    def test_grava_empresa_e_observacao(self, motor: Engine) -> None:
        # Act
        consulta = _consultar(motor, ColetaFalsa(_coleta()))

        # Assert
        assert consulta.origem == "brasilapi"
        assert consulta.idade_horas == 0
        assert consulta.observacao["razao_social"] == "ACME LTDA"
        assert consulta.observacao["coletado_em"] == AGORA_TEXTO
        assert consulta.observacao["bruto_json"] == '{"bruto": true}'
        assert _empresa(motor)["primeira_consulta"] == AGORA_TEXTO

    def test_origem_diz_qual_fonte_respondeu(self, motor: Engine) -> None:
        consulta = _consultar(motor, ColetaFalsa(_coleta(fonte="minhareceita")))

        assert consulta.origem == "minhareceita"
        assert consulta.observacao["fonte"] == "minhareceita"

    def test_gravacao_fica_no_banco_depois_de_fechar(self, url_banco: str) -> None:
        # Sem commit, tudo sumiria ao encerrar a conexão.
        motor = criar_motor(url_banco)
        _consultar(motor, ColetaFalsa(_coleta()))
        motor.dispose()

        outro = criar_motor(url_banco)
        try:
            assert len(_observacoes(outro)) == 1
        finally:
            outro.dispose()


class TestCache:
    def test_duas_consultas_seguidas_fazem_uma_chamada(self, motor: Engine) -> None:
        # Arrange
        coletar = ColetaFalsa(_coleta())
        _consultar(motor, coletar)

        # Act
        depois = _consultar(motor, coletar, agora=AGORA + timedelta(hours=6))

        # Assert
        assert coletar.chamadas == 1
        assert depois.origem == ORIGEM_CACHE
        assert depois.idade_horas == 6
        assert len(_observacoes(motor)) == 1

    def test_cache_vencido_chama_de_novo_e_acrescenta_observacao(self, motor: Engine) -> None:
        coletar = ColetaFalsa(_coleta(), _coleta())
        _consultar(motor, coletar)

        depois = _consultar(motor, coletar, agora=AGORA + timedelta(hours=TTL_HORAS))

        assert coletar.chamadas == 2
        assert depois.origem == "brasilapi"
        assert len(_observacoes(motor)) == 2

    def test_forcar_ignora_o_cache(self, motor: Engine) -> None:
        coletar = ColetaFalsa(_coleta(), _coleta())
        _consultar(motor, coletar)

        depois = _consultar(motor, coletar, agora=AGORA + timedelta(minutes=1), forcar=True)

        assert coletar.chamadas == 2
        assert depois.origem == "brasilapi"

    def test_nova_coleta_atualiza_ultima_consulta_e_preserva_a_primeira(
        self, motor: Engine
    ) -> None:
        coletar = ColetaFalsa(_coleta(), _coleta())
        _consultar(motor, coletar)

        _consultar(motor, coletar, agora=AGORA + timedelta(days=2))

        empresa = _empresa(motor)
        assert empresa["primeira_consulta"] == AGORA_TEXTO
        assert empresa["ultima_consulta"] == "2026-11-08 12:00:00"


class TestDegradacao:
    def test_fontes_fora_com_observacao_antiga_devolve_a_antiga(self, motor: Engine) -> None:
        # Arrange
        coletar = ColetaFalsa(_coleta(), TodasAsFontesFalharam([ERRO_500]))
        _consultar(motor, coletar)

        # Act
        depois = _consultar(motor, coletar, agora=AGORA + timedelta(days=3))

        # Assert
        assert depois.origem == ORIGEM_CACHE_VENCIDO
        assert depois.idade_horas == 72
        assert depois.observacao["razao_social"] == "ACME LTDA"
        assert len(_observacoes(motor)) == 1

    def test_degradacao_registra_cada_falha(self, motor: Engine) -> None:
        erros = [ERRO_500, ErroDeFonte("minhareceita", "timeout")]
        coletar = ColetaFalsa(_coleta(), TodasAsFontesFalharam(erros))
        _consultar(motor, coletar)

        _consultar(motor, coletar, agora=AGORA + timedelta(days=3))

        assert _falhas(motor) == [
            (CNPJ, "2026-11-09 12:00:00", "brasilapi", "HTTP 500"),
            (CNPJ, "2026-11-09 12:00:00", "minhareceita", "timeout"),
        ]

    def test_sem_observacao_o_erro_sobe_e_a_falha_fica_registrada(self, url_banco: str) -> None:
        # A falha precisa estar gravada mesmo com a exceção subindo.
        motor = criar_motor(url_banco)
        with pytest.raises(TodasAsFontesFalharam):
            _consultar(motor, ColetaFalsa(TodasAsFontesFalharam([ERRO_500])))
        motor.dispose()

        outro = criar_motor(url_banco)
        try:
            assert _falhas(outro) == [(CNPJ, AGORA_TEXTO, "brasilapi", "HTTP 500")]
            assert _empresa(outro) is None
        finally:
            outro.dispose()

    def test_falha_da_primaria_e_registrada_quando_a_reserva_resolve(self, motor: Engine) -> None:
        coleta = _coleta(fonte="minhareceita", erros=(ERRO_500,))

        _consultar(motor, ColetaFalsa(coleta))

        assert _falhas(motor) == [(CNPJ, AGORA_TEXTO, "brasilapi", "HTTP 500")]


class TestNaoEncontrado:
    def test_404_nao_grava_nada_nem_conta_como_falha(self, motor: Engine) -> None:
        with pytest.raises(CnpjNaoEncontrado):
            _consultar(motor, ColetaFalsa(CnpjNaoEncontrado(CNPJ)))

        assert _empresa(motor) is None
        assert _falhas(motor) == []


class TestMudancas:
    def test_situacao_diferente_gera_uma_mudanca(self, motor: Engine) -> None:
        _gravar_observacao(motor, "2026-03-01 10:00:00", situacao="ATIVA")
        _gravar_observacao(motor, "2026-07-15 10:00:00", situacao="BAIXADA")

        assert mudancas(motor, CNPJ) == [
            {
                "campo": "situacao",
                "de": "ATIVA",
                "para": "BAIXADA",
                "quando": "2026-07-15 10:00:00",
            }
        ]

    def test_observacoes_identicas_nao_geram_mudanca(self, motor: Engine) -> None:
        _gravar_observacao(motor, "2026-03-01 10:00:00", situacao="ATIVA")
        _gravar_observacao(motor, "2026-07-15 10:00:00", situacao="ATIVA")

        assert mudancas(motor, CNPJ) == []

    def test_uma_observacao_so_nao_gera_mudanca(self, motor: Engine) -> None:
        _gravar_observacao(motor, "2026-03-01 10:00:00", situacao="ATIVA")

        assert mudancas(motor, CNPJ) == []

    def test_sem_observacoes_nao_gera_mudanca(self, motor: Engine) -> None:
        assert mudancas(motor, CNPJ) == []

    def test_campo_fora_da_lista_nao_e_mudanca(self, motor: Engine) -> None:
        # nome_fantasia e capital não são vigiados: decisão de negócio
        _gravar_observacao(motor, "2026-03-01 10:00:00", nome_fantasia="A", capital_centavos=1)
        _gravar_observacao(motor, "2026-07-15 10:00:00", nome_fantasia="B", capital_centavos=2)

        assert mudancas(motor, CNPJ) == []

    def test_trocar_de_fonte_nao_e_mudanca(self, motor: Engine) -> None:
        _gravar_observacao(motor, "2026-03-01 10:00:00", fonte="brasilapi", situacao="ATIVA")
        _gravar_observacao(motor, "2026-07-15 10:00:00", fonte="minhareceita", situacao="ATIVA")

        assert mudancas(motor, CNPJ) == []

    # Lista escrita à mão de propósito: se viesse de `CAMPOS_VIGIADOS`, tirar um
    # campo do código também o tiraria do teste, e nada reprovaria.
    @pytest.mark.parametrize(
        "campo",
        ["razao_social", "situacao", "porte", "cnae_codigo", "municipio", "uf", "qtd_socios"],
    )
    def test_cada_campo_vigiado_e_detectado(self, motor: Engine, campo: str) -> None:
        # qtd_socios é a única coluna numérica; as outras são texto
        antes, depois = (1, 2) if campo == "qtd_socios" else ("A", "B")
        _gravar_observacao(motor, "2026-03-01 10:00:00", **{campo: antes})
        _gravar_observacao(motor, "2026-07-15 10:00:00", **{campo: depois})

        assert [mudanca["campo"] for mudanca in mudancas(motor, CNPJ)] == [campo]

    def test_mudancas_saem_em_ordem_cronologica(self, motor: Engine) -> None:
        # inseridas fora de ordem de propósito
        _gravar_observacao(motor, "2026-09-01 10:00:00", situacao="BAIXADA")
        _gravar_observacao(motor, "2026-03-01 10:00:00", situacao="ATIVA")
        _gravar_observacao(motor, "2026-07-15 10:00:00", situacao="SUSPENSA")

        resultado = mudancas(motor, CNPJ)

        assert [(m["de"], m["para"]) for m in resultado] == [
            ("ATIVA", "SUSPENSA"),
            ("SUSPENSA", "BAIXADA"),
        ]
