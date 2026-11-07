"""Testes do cliente externo: fallback, retry, timeout e classificação de respostas.

A rede é um `httpx.MockTransport` com um roteiro de respostas por fonte, e
`esperar` é falso: os testes contam chamadas e esperas, sem dormir e sem
internet.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.cliente import (
    CnpjNaoEncontrado,
    Coleta,
    ErroDeFonte,
    TodasAsFontesFalharam,
    consultar_externo,
)
from src.config import Settings
from src.fontes.base import normalizar

CNPJ = "11222333000181"
PRIMARIA = "primaria.exemplo"
RESERVA = "reserva.exemplo"
TIMEOUT = 8

Passo = int | httpx.Response | Exception


class RedeFalsa:
    """Roteiro de respostas por host, consumido em ordem, que conta as chamadas.

    Cada passo é um status, uma `httpx.Response` pronta ou uma exceção. Uma
    chamada além do roteiro estoura `IndexError` e reprova o teste.
    """

    def __init__(self, primaria: tuple[Passo, ...] = (), reserva: tuple[Passo, ...] = ()) -> None:
        self.roteiro = {PRIMARIA: list(primaria), RESERVA: list(reserva)}
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        passo = self.roteiro[pedido.url.host].pop(0)
        if isinstance(passo, Exception):
            raise passo
        return httpx.Response(passo) if isinstance(passo, int) else passo

    def chamadas(self, host: str) -> int:
        return sum(1 for pedido in self.pedidos if pedido.url.host == host)


@pytest.fixture
def ok(exemplo_brasilapi: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=exemplo_brasilapi)


def _consultar(rede: RedeFalsa, esperas: list[float] | None = None) -> Coleta:
    config = Settings(
        _env_file=None,  # type: ignore[call-arg]
        brasilapi_base_url=f"https://{PRIMARIA}/api",
        minhareceita_base_url=f"https://{RESERVA}",
        http_timeout_segundos=TIMEOUT,
    )
    esperar = [].append if esperas is None else esperas.append
    with httpx.Client(transport=httpx.MockTransport(rede)) as http:
        return consultar_externo(CNPJ, http=http, config=config, esperar=esperar)


class TestSucesso:
    def test_usa_a_primaria_quando_ela_responde(
        self, ok: httpx.Response, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        # Arrange
        rede = RedeFalsa(primaria=(ok,))
        esperas: list[float] = []

        # Act
        coleta = _consultar(rede, esperas)

        # Assert
        assert coleta.fonte == "brasilapi"
        assert coleta.dados == normalizar(exemplo_brasilapi)
        assert coleta.erros == ()
        assert rede.chamadas(PRIMARIA) == 1
        assert rede.chamadas(RESERVA) == 0
        assert esperas == []

    def test_guarda_a_resposta_inteira_como_veio(
        self, ok: httpx.Response, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        coleta = _consultar(RedeFalsa(primaria=(ok,)))

        assert json.loads(coleta.bruto_json) == exemplo_brasilapi

    def test_aplica_o_timeout_da_configuracao(self, ok: httpx.Response) -> None:
        rede = RedeFalsa(primaria=(ok,))

        _consultar(rede)

        assert rede.pedidos[0].extensions["timeout"]["read"] == TIMEOUT


class TestFallback:
    def test_primaria_com_500_cai_na_reserva(self, ok: httpx.Response) -> None:
        rede = RedeFalsa(primaria=(500, 500, 500), reserva=(ok,))

        coleta = _consultar(rede)

        assert coleta.fonte == "minhareceita"
        assert rede.chamadas(PRIMARIA) == 3
        assert rede.chamadas(RESERVA) == 1

    def test_fallback_preserva_as_falhas_da_primaria(self, ok: httpx.Response) -> None:
        # O dado veio, mas a fonte primária caiu: isso precisa chegar à
        # tabela de falhas, ou "a fonte anda ruim" vira chute.
        coleta = _consultar(RedeFalsa(primaria=(500, 503, 502), reserva=(ok,)))

        assert coleta.erros == (
            ErroDeFonte("brasilapi", "HTTP 500"),
            ErroDeFonte("brasilapi", "HTTP 503"),
            ErroDeFonte("brasilapi", "HTTP 502"),
        )

    def test_espera_cresce_entre_as_tentativas(self, ok: httpx.Response) -> None:
        # Depois da terceira não há espera: a próxima chamada é em outra fonte.
        esperas: list[float] = []

        _consultar(RedeFalsa(primaria=(500, 500, 500), reserva=(ok,)), esperas)

        assert esperas == [2, 4]

    @pytest.mark.parametrize(
        ("erro", "motivo"),
        [
            (httpx.ConnectTimeout("simulado"), "timeout"),
            (httpx.ReadTimeout("simulado"), "timeout"),
            (httpx.ConnectError("simulado"), "erro de rede: ConnectError"),
        ],
        ids=["connect-timeout", "read-timeout", "connect-error"],
    )
    def test_falha_de_rede_e_repetida_e_cai_na_reserva(
        self, ok: httpx.Response, erro: Exception, motivo: str
    ) -> None:
        rede = RedeFalsa(primaria=(erro, erro, erro), reserva=(ok,))

        coleta = _consultar(rede)

        assert coleta.fonte == "minhareceita"
        assert rede.chamadas(PRIMARIA) == 3
        assert coleta.erros[0] == ErroDeFonte("brasilapi", motivo)

    def test_primaria_que_se_recupera_nao_aciona_a_reserva(self, ok: httpx.Response) -> None:
        rede = RedeFalsa(primaria=(500, ok))
        esperas: list[float] = []

        coleta = _consultar(rede, esperas)

        assert coleta.fonte == "brasilapi"
        assert rede.chamadas(RESERVA) == 0
        assert esperas == [2]
        assert coleta.erros == (ErroDeFonte("brasilapi", "HTTP 500"),)


class TestNaoEncontrado:
    def test_404_nao_vira_retry_nem_fallback(self) -> None:
        rede = RedeFalsa(primaria=(404,))
        esperas: list[float] = []

        with pytest.raises(CnpjNaoEncontrado):
            _consultar(rede, esperas)

        assert rede.chamadas(PRIMARIA) == 1
        assert rede.chamadas(RESERVA) == 0
        assert esperas == []

    def test_404_da_reserva_tambem_e_resposta(self) -> None:
        with pytest.raises(CnpjNaoEncontrado):
            _consultar(RedeFalsa(primaria=(500, 500, 500), reserva=(404,)))


class TestRateLimit:
    def test_429_espera_e_tenta_de_novo(self, ok: httpx.Response) -> None:
        rede = RedeFalsa(primaria=(429, ok))
        esperas: list[float] = []

        coleta = _consultar(rede, esperas)

        assert coleta.fonte == "brasilapi"
        assert esperas == [2]

    def test_429_persistente_vira_erro_registrado(self, ok: httpx.Response) -> None:
        # Sem registrar, uma fonte que só devolve 429 não deixa rastro.
        coleta = _consultar(RedeFalsa(primaria=(429, 429, 429), reserva=(ok,)))

        assert coleta.fonte == "minhareceita"
        assert coleta.erros == (ErroDeFonte("brasilapi", "HTTP 429"),) * 3


class TestRespostaInesperada:
    @pytest.mark.parametrize("status", [400, 401, 403, 301])
    def test_status_inesperado_passa_para_a_reserva_sem_repetir(
        self, ok: httpx.Response, status: int
    ) -> None:
        # Repetir não muda a resposta, e o corpo de erro não pode virar observação.
        rede = RedeFalsa(primaria=(status,), reserva=(ok,))
        esperas: list[float] = []

        coleta = _consultar(rede, esperas)

        assert coleta.fonte == "minhareceita"
        assert rede.chamadas(PRIMARIA) == 1
        assert esperas == []
        assert coleta.erros == (ErroDeFonte("brasilapi", f"HTTP {status}"),)

    @pytest.mark.parametrize(
        "corpo",
        [b"<html>manutencao</html>", b"[]", b"{}", b'{"razao_social": ""}'],
        ids=["nao-e-json", "lista", "objeto-vazio", "sem-razao-social"],
    )
    def test_200_fora_do_formato_nao_vira_observacao(
        self, ok: httpx.Response, corpo: bytes
    ) -> None:
        rede = RedeFalsa(primaria=(httpx.Response(200, content=corpo),), reserva=(ok,))

        coleta = _consultar(rede)

        assert coleta.fonte == "minhareceita"
        assert coleta.erros == (ErroDeFonte("brasilapi", "resposta fora do formato esperado"),)

    def test_campo_com_tipo_errado_nao_estoura(self, ok: httpx.Response) -> None:
        corpo = {"razao_social": "ACME", "qsa": 5}
        rede = RedeFalsa(primaria=(httpx.Response(200, json=corpo),), reserva=(ok,))

        coleta = _consultar(rede)

        assert coleta.fonte == "minhareceita"


class TestTodasAsFontesFalharam:
    def test_levanta_com_os_erros_de_cada_fonte(self) -> None:
        rede = RedeFalsa(primaria=(500, 500, 500), reserva=(httpx.ConnectError("x"),) * 3)

        with pytest.raises(TodasAsFontesFalharam) as falha:
            _consultar(rede)

        assert falha.value.erros == [
            ErroDeFonte("brasilapi", "HTTP 500"),
            ErroDeFonte("brasilapi", "HTTP 500"),
            ErroDeFonte("brasilapi", "HTTP 500"),
            ErroDeFonte("minhareceita", "erro de rede: ConnectError"),
            ErroDeFonte("minhareceita", "erro de rede: ConnectError"),
            ErroDeFonte("minhareceita", "erro de rede: ConnectError"),
        ]

    def test_cada_fonte_recebe_no_maximo_tres_tentativas(self) -> None:
        rede = RedeFalsa(primaria=(500,) * 3, reserva=(503,) * 3)

        with pytest.raises(TodasAsFontesFalharam):
            _consultar(rede)

        assert rede.chamadas(PRIMARIA) == 3
        assert rede.chamadas(RESERVA) == 3
