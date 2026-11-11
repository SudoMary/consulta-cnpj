"""Testes da tela web, da rota ao HTML.

Passam por todas as peças de verdade, com banco em arquivo temporário. Só a
rede é falsa: um `httpx.MockTransport` que conta as chamadas. Os cenários de
falha usam 403 porque ele não é repetido, e o teste não precisa dormir.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import criar_app
from src.config import Settings
from src.db import criar_motor
from src.repo import inserir_empresa_se_nao_existe, inserir_observacao

CNPJ = "11222333000181"
ANTIGA = "2020-01-01 10:00:00"


class Rede:
    """Responde com `status` e `corpo`, que o teste pode trocar, e conta as chamadas."""

    def __init__(self, status: int, corpo: dict[str, Any] | None = None) -> None:
        self.status = status
        self.corpo = corpo
        self.chamadas = 0

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.chamadas += 1
        return httpx.Response(self.status, json=self.corpo)


@pytest.fixture
def banco_web(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'web.db').as_posix()}"


@pytest.fixture
def rede(exemplo_brasilapi: dict[str, Any]) -> Rede:
    return Rede(200, exemplo_brasilapi)


@pytest.fixture
def cliente(banco_web: str, rede: Rede) -> Iterator[TestClient]:
    config = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=banco_web,
        brasilapi_base_url="https://primaria.exemplo/api",
        minhareceita_base_url="https://reserva.exemplo",
    )
    with TestClient(criar_app(config, transporte=httpx.MockTransport(rede))) as c:
        yield c


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


class TestBusca:
    def test_pagina_inicial_tem_o_formulario(self, cliente: TestClient) -> None:
        resposta = cliente.get("/")

        assert resposta.status_code == 200
        assert 'name="cnpj"' in resposta.text
        assert "Consulte uma empresa pelo CNPJ" in resposta.text

    def test_cnpj_valido_leva_para_a_ficha(self, cliente: TestClient, rede: Rede) -> None:
        resposta = cliente.get("/consulta?cnpj=11.222.333/0001-81", follow_redirects=False)

        assert resposta.status_code == 303
        assert resposta.headers["location"] == f"/empresa/{CNPJ}"
        assert rede.chamadas == 0  # só redireciona; a consulta é na ficha

    def test_cnpj_invalido_volta_com_a_mensagem_e_sem_chamar_a_rede(
        self, cliente: TestClient, rede: Rede
    ) -> None:
        resposta = cliente.get("/consulta?cnpj=11222333000182")

        assert resposta.status_code == 400
        assert "CNPJ inválido" in resposta.text
        assert 'value="11222333000182"' in resposta.text
        assert rede.chamadas == 0


class TestFicha:
    def test_mostra_a_ficha_e_de_onde_veio_o_dado(self, cliente: TestClient) -> None:
        # Act
        resposta = cliente.get(f"/empresa/{CNPJ}")

        # Assert
        html = resposta.text
        assert resposta.status_code == 200
        assert "CAIXA ESCOLAR DA ESCOLA ESTADUAL" in html
        assert "11.222.333/0001-81" in html
        assert "ATIVA" in html
        assert "Consultado agora na BrasilAPI" in html
        assert "85.50-3-01 · Administração de caixas escolares" in html
        assert "R$ 0,00" in html
        assert "Primeira consulta. Nenhuma mudança desde então." in html

    def test_segunda_visita_sai_do_cache(self, cliente: TestClient, rede: Rede) -> None:
        cliente.get(f"/empresa/{CNPJ}")

        resposta = cliente.get(f"/empresa/{CNPJ}")

        assert rede.chamadas == 1
        assert "Do cache, há menos de 1 hora" in resposta.text

    def test_mostra_a_mudanca_na_linha_do_tempo_e_no_destaque(
        self, cliente: TestClient, banco_web: str
    ) -> None:
        _gravar_observacao_antiga(banco_web, situacao="SUSPENSA")

        html = cliente.get(f"/empresa/{CNPJ}").text

        assert "A situação mudou de SUSPENSA para ATIVA." in html
        assert '<del class="ev-de">SUSPENSA</del>' in html
        assert '<ins class="ev-para">ATIVA</ins>' in html

    def test_texto_da_api_e_escapado(
        self, cliente: TestClient, rede: Rede, exemplo_brasilapi: dict[str, Any]
    ) -> None:
        # Dado de terceiro nunca vira HTML: o template escapa tudo.
        rede.corpo = {**exemplo_brasilapi, "razao_social": "<script>alert(1)</script>"}

        html = cliente.get(f"/empresa/{CNPJ}").text

        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)</script>" not in html


class TestErros:
    def test_cnpj_invalido_no_endereco(self, cliente: TestClient, rede: Rede) -> None:
        resposta = cliente.get("/empresa/11222333000182")

        assert resposta.status_code == 400
        assert "CNPJ inválido" in resposta.text
        assert rede.chamadas == 0

    def test_cnpj_inexistente(self, cliente: TestClient, rede: Rede) -> None:
        rede.status, rede.corpo = 404, {"message": "não encontrado"}

        resposta = cliente.get(f"/empresa/{CNPJ}")

        assert resposta.status_code == 404
        assert "CNPJ não encontrado na base da Receita." in resposta.text

    def test_sem_fontes_e_sem_historico(self, cliente: TestClient, rede: Rede) -> None:
        rede.status = 403

        resposta = cliente.get(f"/empresa/{CNPJ}")

        assert resposta.status_code == 503
        assert "As fontes estão fora do ar" in resposta.text

    def test_sem_fontes_com_historico_entrega_o_antigo_com_aviso(
        self, cliente: TestClient, rede: Rede, banco_web: str
    ) -> None:
        # O GUIA: derrubar a internet e recarregar devolve o cache com aviso, não erro.
        _gravar_observacao_antiga(banco_web, situacao="ATIVA")
        rede.status = 403

        resposta = cliente.get(f"/empresa/{CNPJ}")

        assert resposta.status_code == 200
        assert "As fontes estão fora do ar agora." in resposta.text
        assert "ACME LTDA" in resposta.text


class TestModoEscuro:
    def test_estilo_tem_tema_escuro_pelo_sistema_e_pela_escolha(self, cliente: TestClient) -> None:
        css = cliente.get("/estatico/estilo.css").text

        assert "@media (prefers-color-scheme: dark)" in css
        assert ':root[data-theme="dark"]' in css

    def test_pagina_tem_o_botao_de_tema(self, cliente: TestClient) -> None:
        html = cliente.get("/").text

        assert 'id="alternar-tema"' in html
        assert 'localStorage.getItem("tema")' in html


class TestSaude:
    def test_responde_ok(self, cliente: TestClient) -> None:
        assert cliente.get("/saude").json() == {"status": "ok"}
