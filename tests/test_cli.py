"""Testes da linha de comando, do argumento à tela.

Passam por todas as peças de verdade, com banco em arquivo temporário. Só a
rede é falsa: um `httpx.MockTransport` que conta as chamadas. Os cenários de
falha usam 403 porque ele não é repetido, e o teste não precisa dormir.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

import anthropic
import httpx
import httpx2
import pytest

from src.cli import formatar_mudancas, main
from src.config import Settings
from src.db import criar_motor
from src.repo import cnpjs_acompanhados, inserir_empresa_se_nao_existe, inserir_observacao
from tests.falsos import ClienteIAFalso, resposta_texto

CNPJ = "11222333000181"
ANTIGA = "2020-01-01 10:00:00"


class Rede:
    """Responde sempre a mesma coisa e conta as chamadas."""

    def __init__(self, status: int, corpo: dict[str, Any] | None = None) -> None:
        self.status = status
        self.corpo = corpo
        self.chamadas = 0

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.chamadas += 1
        return httpx.Response(self.status, json=self.corpo)


@pytest.fixture
def banco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Aponta a configuração para um banco temporário e fontes fictícias."""
    caminho = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", caminho)
    monkeypatch.setenv("BRASILAPI_BASE_URL", "https://primaria.exemplo/api")
    monkeypatch.setenv("MINHARECEITA_BASE_URL", "https://reserva.exemplo")
    return caminho


@pytest.fixture
def rede_ok(exemplo_brasilapi: dict[str, Any]) -> Rede:
    return Rede(200, exemplo_brasilapi)


def _rodar(rede: Rede, *argumentos: str) -> int:
    return main(["consultar", *argumentos], transporte=httpx.MockTransport(rede))


def _gravar_observacao_antiga(url: str, **dados: Any) -> None:
    motor = criar_motor(url)
    try:
        with motor.begin() as con:
            inserir_empresa_se_nao_existe(con, CNPJ, ANTIGA)
            inserir_observacao(
                con,
                cnpj=CNPJ,
                dados={"razao_social": "ACME LTDA", **dados},
                fonte="brasilapi",
                coletado_em=ANTIGA,
                bruto_json="{}",
            )
    finally:
        motor.dispose()


class TestConsultar:
    def test_mostra_a_ficha_e_a_origem(
        self, banco: str, rede_ok: Rede, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Act
        codigo = _rodar(rede_ok, "11.222.333/0001-81")

        # Assert
        saida = capsys.readouterr().out
        assert codigo == 0
        assert "11.222.333/0001-81" in saida
        assert "CAIXA ESCOLAR" in saida
        assert "ATIVA" in saida
        assert "Administração de caixas escolares" in saida
        assert "R$ 0,00" in saida
        assert "consultado agora na BrasilAPI" in saida
        assert "Nenhuma mudança detectada." in saida

    def test_segunda_consulta_sai_do_cache(
        self, banco: str, rede_ok: Rede, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _rodar(rede_ok, CNPJ)
        capsys.readouterr()

        codigo = _rodar(rede_ok, CNPJ)

        assert codigo == 0
        assert rede_ok.chamadas == 1
        assert "do cache, há menos de 1 hora" in capsys.readouterr().out

    def test_forcar_ignora_o_cache(self, banco: str, rede_ok: Rede) -> None:
        _rodar(rede_ok, CNPJ)

        _rodar(rede_ok, CNPJ, "--forcar")

        assert rede_ok.chamadas == 2

    def test_mostra_a_mudanca_detectada(
        self, banco: str, rede_ok: Rede, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _gravar_observacao_antiga(banco, situacao="SUSPENSA")

        _rodar(rede_ok, CNPJ)

        assert "situacao: SUSPENSA -> ATIVA" in capsys.readouterr().out


class TestErros:
    def test_cnpj_invalido_nao_chama_a_rede(
        self, banco: str, rede_ok: Rede, capsys: pytest.CaptureFixture[str]
    ) -> None:
        codigo = _rodar(rede_ok, "11222333000182")

        capturado = capsys.readouterr()
        assert codigo == 1
        assert rede_ok.chamadas == 0
        assert "CNPJ inválido" in capturado.err
        assert capturado.out == ""

    def test_cnpj_inexistente_tem_mensagem_propria(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        codigo = _rodar(Rede(404, {"message": "não encontrado"}), CNPJ)

        assert codigo == 1
        assert "não encontrado" in capsys.readouterr().err

    def test_sem_fontes_e_sem_historico_o_erro_e_claro(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # O GUIA pede erro claro aqui, não traceback.
        codigo = _rodar(Rede(403), CNPJ)

        assert codigo == 1
        assert "fontes" in capsys.readouterr().err

    def test_sem_fontes_com_historico_entrega_o_antigo_com_aviso(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _gravar_observacao_antiga(banco, situacao="ATIVA")

        codigo = _rodar(Rede(403), CNPJ)

        saida = capsys.readouterr().out
        assert codigo == 0
        assert "ACME LTDA" in saida
        assert "as fontes estão fora do ar agora" in saida


class TestFormatacao:
    def test_lista_de_mudancas(self) -> None:
        lista = [{"campo": "uf", "de": "SP", "para": "RJ", "quando": "2026-07-15 10:00:00"}]

        assert formatar_mudancas(lista) == (
            "Mudanças detectadas (horário UTC):\n  2026-07-15 10:00:00  uf: SP -> RJ"
        )


class TestAcompanhar:
    def _acompanhados(self, url: str) -> list[str]:
        motor = criar_motor(url)
        try:
            with motor.connect() as con:
                return cnpjs_acompanhados(con)
        finally:
            motor.dispose()

    def test_inclui_a_empresa_na_coleta_diaria(
        self, banco: str, rede_ok: Rede, capsys: pytest.CaptureFixture[str]
    ) -> None:
        codigo = main(["acompanhar", "11.222.333/0001-81"], transporte=httpx.MockTransport(rede_ok))

        assert codigo == 0
        assert self._acompanhados(banco) == [CNPJ]
        assert "Acompanhando 11.222.333/0001-81" in capsys.readouterr().out

    def test_cnpj_invalido_nao_inclui_nada(
        self, banco: str, rede_ok: Rede, capsys: pytest.CaptureFixture[str]
    ) -> None:
        codigo = main(["acompanhar", "11222333000182"], transporte=httpx.MockTransport(rede_ok))

        assert codigo == 1
        assert rede_ok.chamadas == 0
        assert self._acompanhados(banco) == []
        assert "CNPJ inválido" in capsys.readouterr().err


class TestPerguntar:
    """O cliente da API é falso: nenhum teste chama o Claude de verdade."""

    def test_imprime_a_resposta_do_assistente(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cliente = ClienteIAFalso(resposta_texto("Nenhuma empresa mudou este mês."))

        codigo = main(["perguntar", "O que mudou este mês?"], cliente_ia=cliente)

        assert codigo == 0
        assert capsys.readouterr().out.strip() == "Nenhuma empresa mudou este mês."
        assert cliente.chamadas == 1

    def test_sem_chave_explica_como_ligar(
        self, banco: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Um .env da máquina de quem roda os testes não pode ligar o assistente.
        monkeypatch.setattr("src.cli.Settings", partial(Settings, _env_file=None))

        codigo = main(["perguntar", "O que mudou?"])

        assert codigo == 1
        assert "ANTHROPIC_API_KEY" in capsys.readouterr().err

    def test_pergunta_vazia_nao_chama_o_modelo(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cliente = ClienteIAFalso()

        codigo = main(["perguntar", "   "], cliente_ia=cliente)

        assert codigo == 1
        assert cliente.chamadas == 0
        assert "Escreva uma pergunta" in capsys.readouterr().err

    def test_api_fora_do_ar_tem_mensagem_clara(
        self, banco: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pedido = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        cliente = ClienteIAFalso(anthropic.APIConnectionError(request=pedido))

        codigo = main(["perguntar", "O que mudou?"], cliente_ia=cliente)

        assert codigo == 1
        assert "fora do ar" in capsys.readouterr().err
