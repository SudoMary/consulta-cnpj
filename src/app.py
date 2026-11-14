"""Tela web: `uvicorn src.app:app`.

Liga as peças e entrega HTML montado no servidor, sem framework de front. Como
na linha de comando, nenhuma regra de negócio mora aqui: validação, cache,
fallback e detecção de mudança vêm do serviço, e o conteúdo de cada página vem
de `telas.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .assistente import (
    AssistenteIndisponivel,
    criar_cliente,
    perguntar,
    perguntas_restantes,
)
from .cliente import CnpjNaoEncontrado, TodasAsFontesFalharam, consultar_externo
from .config import Settings
from .db import criar_motor
from .formatacao import MENSAGEM_NAO_ENCONTRADO, MENSAGEM_SEM_FONTES
from .servico import RegraDeNegocio, acompanhar, consultar, historico, painel, validar_cnpj
from .telas import pagina_da_empresa, pagina_do_assistente, pagina_do_painel

_PASTA = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=_PASTA / "templates")


def criar_app(
    config: Settings | None = None, *, transporte: httpx.BaseTransport | None = None
) -> FastAPI:
    """Monta a aplicação. `transporte` existe para os testes trocarem a rede."""
    config = config or Settings()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        app.state.motor = criar_motor(config.url_banco)
        app.state.http = httpx.Client(transport=transporte)
        try:
            yield
        finally:
            app.state.http.close()
            app.state.motor.dispose()

    app = FastAPI(
        title="Consulta CNPJ",
        lifespan=ciclo_de_vida,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount("/estatico", StaticFiles(directory=_PASTA / "estatico"), name="estatico")

    def _inicio(request: Request, contexto: dict[str, Any], status_code: int = 200) -> Response:
        contexto["acompanhadas"] = pagina_do_painel(painel(request.app.state.motor))
        return _pagina(request, "inicio.html", contexto, status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request) -> Response:
        return _inicio(request, {})

    @app.get("/consulta")
    def consulta(request: Request, cnpj: str = "") -> Response:
        try:
            digitos = validar_cnpj(cnpj)
        except RegraDeNegocio as erro:
            return _inicio(request, {"erro": str(erro), "cnpj": cnpj}, status_code=400)
        return RedirectResponse(f"/empresa/{digitos}", status_code=303)

    @app.get("/acompanhadas", response_class=HTMLResponse)
    def acompanhadas(request: Request, filtro: str = "todas") -> Response:
        pagina = pagina_do_painel(painel(request.app.state.motor), filtro)
        return _pagina(request, "acompanhadas.html", {"p": pagina})

    @app.post("/empresa/{cnpj}/acompanhar")
    def acompanhar_empresa(request: Request, cnpj: str) -> Response:
        coletar = partial(consultar_externo, http=request.app.state.http, config=config)
        try:
            resultado = acompanhar(
                cnpj,
                motor=request.app.state.motor,
                coletar=coletar,
                ttl_horas=config.cache_ttl_horas,
            )
        except RegraDeNegocio as erro:
            return _erro(request, 400, "Não foi possível acompanhar", str(erro))
        except CnpjNaoEncontrado:
            return _erro(request, 404, "CNPJ não encontrado", MENSAGEM_NAO_ENCONTRADO)
        except TodasAsFontesFalharam:
            return _erro(request, 503, "Fontes fora do ar", MENSAGEM_SEM_FONTES)
        return RedirectResponse(f"/empresa/{resultado.observacao['cnpj']}", status_code=303)

    @app.get("/empresa/{cnpj}", response_class=HTMLResponse)
    def empresa(request: Request, cnpj: str) -> Response:
        motor = request.app.state.motor
        coletar = partial(consultar_externo, http=request.app.state.http, config=config)
        try:
            resultado = consultar(
                cnpj, motor=motor, coletar=coletar, ttl_horas=config.cache_ttl_horas
            )
        except RegraDeNegocio as erro:
            return _erro(request, 400, "CNPJ inválido", str(erro))
        except CnpjNaoEncontrado:
            return _erro(request, 404, "CNPJ não encontrado", MENSAGEM_NAO_ENCONTRADO)
        except TodasAsFontesFalharam:
            return _erro(request, 503, "Fontes fora do ar", MENSAGEM_SEM_FONTES)

        pagina = pagina_da_empresa(resultado, historico(motor, resultado.observacao["cnpj"]))
        return _pagina(request, "empresa.html", {"p": pagina})

    def _assistente(
        request: Request, modelo: str | None, status_code: int = 200, **conteudo: Any
    ) -> Response:
        restantes = perguntas_restantes(
            request.app.state.motor, limite_diario=config.assistente_limite_diario
        )
        pagina = pagina_do_assistente(modelo=modelo, restantes=restantes, **conteudo)
        return _pagina(request, "assistente.html", {"p": pagina}, status_code=status_code)

    @app.get("/assistente", response_class=HTMLResponse)
    def assistente(request: Request) -> Response:
        escolhido = criar_cliente(config, http=request.app.state.http)
        return _assistente(request, escolhido[1] if escolhido else None)

    @app.post("/assistente", response_class=HTMLResponse)
    def perguntar_ao_assistente(request: Request, pergunta: str = Form("")) -> Response:
        escolhido = criar_cliente(config, http=request.app.state.http)
        if escolhido is None:
            return _assistente(
                request, None, 503, erro="O assistente está desligado neste ambiente."
            )
        cliente, modelo = escolhido
        try:
            resposta = perguntar(
                pergunta,
                motor=request.app.state.motor,
                cliente=cliente,
                modelo=modelo,
                limite_diario=config.assistente_limite_diario,
            )
        except RegraDeNegocio as erro:
            return _assistente(request, modelo, 400, pergunta=pergunta, erro=str(erro))
        except AssistenteIndisponivel as erro:
            return _assistente(request, modelo, 503, pergunta=pergunta, erro=str(erro))
        return _assistente(request, modelo, pergunta=pergunta.strip(), resposta=resposta.texto)

    @app.get("/saude")
    def saude() -> dict[str, str]:
        """Usado pela hospedagem para saber se o processo está de pé."""
        return {"status": "ok"}

    return app


def _pagina(
    request: Request, nome: str, contexto: dict[str, Any] | None = None, status_code: int = 200
) -> Response:
    return _TEMPLATES.TemplateResponse(request, nome, contexto or {}, status_code=status_code)


def _erro(request: Request, status_code: int, titulo: str, mensagem: str) -> Response:
    contexto = {"titulo": titulo, "mensagem": mensagem}
    return _pagina(request, "erro.html", contexto, status_code=status_code)


app = criar_app()
