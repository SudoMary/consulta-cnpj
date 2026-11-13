"""Testes do assistente (src/assistente.py).

O banco é de verdade, nos dois dialetos. A API do Claude é um cliente falso
que segue um roteiro: nenhum teste chama a rede nem gasta dinheiro.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import anthropic
import httpx2
import pytest
from sqlalchemy import Engine, text

from src.assistente import (
    BETA_FALLBACK,
    DEFINICOES,
    MAXIMO_DE_CHAMADAS,
    MENSAGEM_RECUSA,
    MENSAGEM_SEM_CONCLUSAO,
    TAMANHO_MAXIMO_DA_PERGUNTA,
    AssistenteIndisponivel,
    buscar_empresas,
    listar_acompanhadas,
    mudancas_desde,
    perguntar,
    ver_empresa,
)
from src.repo import (
    inserir_empresa_se_nao_existe,
    inserir_observacao,
    marcar_acompanhamento,
    registrar_pergunta,
)
from src.servico import RegraDeNegocio
from tests.falsos import ClienteIAFalso, resposta_ferramentas, resposta_recusa, resposta_texto

CNPJ = "11222333000181"
OUTRO_CNPJ = "11444777000161"
AGORA = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
ANTES = "2026-10-01 12:00:00"
ONTEM = "2026-11-11 15:00:00"


def _gravar(motor: Engine, cnpj: str, quando: str, **dados: Any) -> None:
    with motor.begin() as con:
        inserir_empresa_se_nao_existe(con, cnpj, quando)
        inserir_observacao(
            con,
            cnpj=cnpj,
            dados={"razao_social": "ACME LTDA", "situacao": "ATIVA", **dados},
            fonte="brasilapi",
            coletado_em=quando,
            bruto_json="{}",
        )


def _acompanhar(motor: Engine, cnpj: str) -> None:
    with motor.begin() as con:
        marcar_acompanhamento(con, cnpj, acompanhando=True)


def _perguntar(
    motor: Engine, cliente: ClienteIAFalso, texto: str = "Como está a ACME?", limite: int = 20
) -> str:
    return perguntar(
        texto,
        motor=motor,
        cliente=cliente,  # type: ignore[arg-type]
        modelo="modelo-teste",
        limite_diario=limite,
        agora=AGORA,
    ).texto


def _registrar_pergunta(motor: Engine, feita_em: str) -> None:
    with motor.begin() as con:
        registrar_pergunta(
            con,
            feita_em=feita_em,
            texto="?",
            modelo="modelo-teste",
            desfecho="respondida",
            chamadas=1,
            tokens_entrada=1,
            tokens_saida=1,
        )


def _perguntas_gravadas(motor: Engine) -> list[dict[str, Any]]:
    with motor.connect() as con:
        linhas = con.execute(text("SELECT * FROM pergunta ORDER BY id")).mappings()
        return [dict(linha) for linha in linhas]


def _resultados(pedido: dict[str, Any]) -> list[dict[str, Any]]:
    """Os `tool_result` que o assistente mandou na última mensagem do pedido."""
    ultima = pedido["messages"][-1]
    assert ultima["role"] == "user"
    return ultima["content"]


def _erro_de_conexao() -> anthropic.APIConnectionError:
    pedido = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=pedido)


def _chave_recusada() -> anthropic.AuthenticationError:
    pedido = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resposta = httpx2.Response(401, request=pedido)
    return anthropic.AuthenticationError("chave inválida", response=resposta, body=None)


class TestAntesDeChamarOModelo:
    def test_pergunta_vazia_nao_chama_o_modelo(self, motor: Engine) -> None:
        cliente = ClienteIAFalso()

        with pytest.raises(RegraDeNegocio):
            _perguntar(motor, cliente, "   ")

        assert cliente.chamadas == 0

    def test_pergunta_longa_demais_nao_chama_o_modelo(self, motor: Engine) -> None:
        cliente = ClienteIAFalso()

        with pytest.raises(RegraDeNegocio, match=str(TAMANHO_MAXIMO_DA_PERGUNTA)):
            _perguntar(motor, cliente, "a" * (TAMANHO_MAXIMO_DA_PERGUNTA + 1))

        assert cliente.chamadas == 0

    def test_limite_diario_atingido_nao_chama_o_modelo(self, motor: Engine) -> None:
        for _ in range(2):
            _registrar_pergunta(motor, "2026-11-12 08:00:00")
        cliente = ClienteIAFalso()

        with pytest.raises(RegraDeNegocio, match="limite"):
            _perguntar(motor, cliente, limite=2)

        assert cliente.chamadas == 0

    def test_perguntas_de_ontem_em_brasilia_nao_contam_no_limite(self, motor: Engine) -> None:
        # 02:59 UTC do dia 12 ainda é dia 11 em Brasília.
        for _ in range(2):
            _registrar_pergunta(motor, "2026-11-12 02:59:59")
        cliente = ClienteIAFalso(resposta_texto("Oi."))

        assert _perguntar(motor, cliente, limite=2) == "Oi."


class TestConversa:
    def test_resposta_direta_devolve_o_texto_e_registra_a_pergunta(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(resposta_texto("Só respondo sobre as empresas do site."))

        texto = _perguntar(motor, cliente, "  Qual a capital da França?  ")

        assert texto == "Só respondo sobre as empresas do site."
        [registro] = _perguntas_gravadas(motor)
        assert registro["texto"] == "Qual a capital da França?"
        assert registro["feita_em"] == "2026-11-12 15:00:00"
        assert registro["modelo"] == "modelo-teste"
        assert registro["desfecho"] == "respondida"
        assert (registro["chamadas"], registro["tokens_entrada"], registro["tokens_saida"]) == (
            1,
            100,
            20,
        )

    def test_pedido_leva_modelo_ferramentas_e_fallback(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(resposta_texto("Oi."))

        _perguntar(motor, cliente)

        [pedido] = cliente.pedidos
        assert pedido["model"] == "modelo-teste"
        assert pedido["system"]
        assert pedido["tools"] == DEFINICOES
        # Se o modelo recusar, a própria API tenta de novo num modelo reserva.
        assert pedido["fallbacks"] == "default"
        assert BETA_FALLBACK in pedido["betas"]

    def test_ferramentas_tem_esquema_estrito(self) -> None:
        for definicao in DEFINICOES:
            assert definicao["strict"] is True
            assert definicao["input_schema"]["additionalProperties"] is False

    def test_a_data_de_hoje_vai_com_a_pergunta(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(resposta_texto("Oi."))

        _perguntar(motor, cliente, "O que mudou este mês?")

        [mensagem] = cliente.pedidos[0]["messages"]
        assert "2026-11-12" in mensagem["content"]
        assert "O que mudou este mês?" in mensagem["content"]

    def test_executa_a_ferramenta_e_devolve_o_resultado_ao_modelo(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ONTEM, razao_social="ACME LTDA")
        cliente = ClienteIAFalso(
            resposta_ferramentas(("ver_empresa", {"cnpj": CNPJ})),
            resposta_texto("A ACME LTDA está ativa."),
        )

        texto = _perguntar(motor, cliente)

        assert texto == "A ACME LTDA está ativa."
        segundo = cliente.pedidos[1]
        # O turno do modelo volta inteiro, antes dos resultados.
        assert segundo["messages"][1]["role"] == "assistant"
        [resultado] = _resultados(segundo)
        assert resultado["tool_use_id"] == "toolu_1"
        assert not resultado.get("is_error")
        assert json.loads(resultado["content"])["razao_social"] == "ACME LTDA"

    def test_varias_ferramentas_na_mesma_rodada_voltam_juntas(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ONTEM)
        _gravar(motor, OUTRO_CNPJ, ONTEM, razao_social="OUTRA SA")
        cliente = ClienteIAFalso(
            resposta_ferramentas(
                ("ver_empresa", {"cnpj": CNPJ}), ("ver_empresa", {"cnpj": OUTRO_CNPJ})
            ),
            resposta_texto("As duas estão ativas."),
        )

        _perguntar(motor, cliente)

        resultados = _resultados(cliente.pedidos[1])
        assert [r["tool_use_id"] for r in resultados] == ["toolu_1", "toolu_2"]

    def test_erro_na_ferramenta_volta_ao_modelo_marcado_como_erro(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(
            resposta_ferramentas(("ver_empresa", {"cnpj": "123"})),
            resposta_texto("Esse CNPJ não é válido."),
        )

        texto = _perguntar(motor, cliente)

        assert texto == "Esse CNPJ não é válido."
        [resultado] = _resultados(cliente.pedidos[1])
        assert resultado["is_error"] is True
        assert "CNPJ inválido" in resultado["content"]

    def test_ferramenta_desconhecida_volta_como_erro(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(
            resposta_ferramentas(("apagar_tudo", {})),
            resposta_texto("Não consigo fazer isso."),
        )

        _perguntar(motor, cliente)

        [resultado] = _resultados(cliente.pedidos[1])
        assert resultado["is_error"] is True

    def test_tokens_de_todas_as_chamadas_sao_somados(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(
            resposta_ferramentas(("listar_acompanhadas", {})),
            resposta_texto("Nenhuma empresa acompanhada."),
        )

        _perguntar(motor, cliente)

        [registro] = _perguntas_gravadas(motor)
        assert (registro["chamadas"], registro["tokens_entrada"], registro["tokens_saida"]) == (
            2,
            200,
            40,
        )


class TestQuandoNaoHaResposta:
    def test_recusa_vira_mensagem_pronta(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(resposta_recusa())

        assert _perguntar(motor, cliente) == MENSAGEM_RECUSA
        assert _perguntas_gravadas(motor)[0]["desfecho"] == "recusada"

    def test_para_depois_do_maximo_de_chamadas(self, motor: Engine) -> None:
        roteiro = [resposta_ferramentas(("listar_acompanhadas", {}))] * MAXIMO_DE_CHAMADAS
        cliente = ClienteIAFalso(*roteiro)

        assert _perguntar(motor, cliente) == MENSAGEM_SEM_CONCLUSAO
        assert cliente.chamadas == MAXIMO_DE_CHAMADAS
        assert _perguntas_gravadas(motor)[0]["desfecho"] == "sem_conclusao"

    def test_resposta_cortada_no_meio_nao_e_entregue(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(resposta_texto("A ACME está", stop_reason="max_tokens"))

        assert _perguntar(motor, cliente) == MENSAGEM_SEM_CONCLUSAO

    def test_api_fora_do_ar_levanta_indisponivel_e_registra(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(_erro_de_conexao())

        with pytest.raises(AssistenteIndisponivel, match="fora do ar"):
            _perguntar(motor, cliente)

        [registro] = _perguntas_gravadas(motor)
        assert registro["desfecho"] == "erro"
        assert registro["chamadas"] == 1

    def test_chave_recusada_diz_que_e_configuracao(self, motor: Engine) -> None:
        cliente = ClienteIAFalso(_chave_recusada())

        with pytest.raises(AssistenteIndisponivel, match="chave"):
            _perguntar(motor, cliente)


class TestListarAcompanhadas:
    def test_so_as_acompanhadas_com_situacao_e_estado(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ONTEM, razao_social="ACME LTDA", situacao="ATIVA")
        _gravar(motor, OUTRO_CNPJ, ONTEM, razao_social="OUTRA SA")
        _acompanhar(motor, CNPJ)

        resultado = listar_acompanhadas(motor, agora=AGORA)

        assert resultado["total"] == 1
        [empresa] = resultado["empresas"]
        assert empresa["cnpj"] == "11.222.333/0001-81"
        assert empresa["razao_social"] == "ACME LTDA"
        assert empresa["situacao"] == "ATIVA"
        assert empresa["estado"] == "sem novidades"

    def test_mudanca_recente_aparece(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ANTES, situacao="ATIVA")
        _gravar(motor, CNPJ, ONTEM, situacao="BAIXADA")
        _acompanhar(motor, CNPJ)

        [empresa] = listar_acompanhadas(motor, agora=AGORA)["empresas"]

        assert empresa["estado"].startswith("mudou")
        assert empresa["ultima_mudanca"] == {
            "quando": "11/11/2026, 12:00",
            "campo": "Situação",
            "de": "ATIVA",
            "para": "BAIXADA",
        }


class TestBuscarEmpresas:
    def test_acha_pelo_nome_sem_ligar_para_maiusculas_e_acentos(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ONTEM, razao_social="CONSTRUÇÕES SÃO JOÃO LTDA")
        _gravar(motor, OUTRO_CNPJ, ONTEM, razao_social="OUTRA SA")

        resultado = buscar_empresas(motor, agora=AGORA, texto="construcoes sao joao")

        assert [e["cnpj"] for e in resultado["empresas"]] == ["11.222.333/0001-81"]

    def test_acha_pelo_nome_fantasia(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ONTEM, razao_social="X LTDA", nome_fantasia="Padaria Pão Quente")

        resultado = buscar_empresas(motor, agora=AGORA, texto="pao quente")

        assert resultado["total_encontradas"] == 1

    def test_acha_pelo_cnpj_com_ou_sem_pontuacao(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ONTEM)
        _gravar(motor, OUTRO_CNPJ, ONTEM)

        for texto in ("11.222.333", "11222333"):
            resultado = buscar_empresas(motor, agora=AGORA, texto=texto)
            assert [e["cnpj"] for e in resultado["empresas"]] == ["11.222.333/0001-81"]

    def test_usa_a_observacao_mais_recente(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ANTES, razao_social="NOME ANTIGO")
        _gravar(motor, CNPJ, ONTEM, razao_social="NOME NOVO")

        assert buscar_empresas(motor, agora=AGORA, texto="antigo")["total_encontradas"] == 0

    def test_texto_vazio_e_erro(self, motor: Engine) -> None:
        with pytest.raises(RegraDeNegocio):
            buscar_empresas(motor, agora=AGORA, texto="  ")


class TestVerEmpresa:
    def test_empresa_que_nunca_foi_consultada(self, motor: Engine) -> None:
        resultado = ver_empresa(motor, agora=AGORA, cnpj=CNPJ)

        assert resultado["encontrada"] is False
        assert "consult" in resultado["mensagem"]

    def test_dados_mais_recentes_e_mudancas(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, ANTES, situacao="ATIVA", capital_centavos=150000)
        _gravar(motor, CNPJ, ONTEM, situacao="BAIXADA", capital_centavos=150000)
        _acompanhar(motor, CNPJ)

        resultado = ver_empresa(motor, agora=AGORA, cnpj="11.222.333/0001-81")

        assert resultado["encontrada"] is True
        assert resultado["situacao"] == "BAIXADA"
        assert resultado["capital_social"] == "R$ 1.500,00"
        assert resultado["dados_de"] == "11/11/2026, 12:00"
        assert resultado["acompanhada"] is True
        assert resultado["mudancas"] == [
            {"quando": "11/11/2026, 12:00", "campo": "Situação", "de": "ATIVA", "para": "BAIXADA"}
        ]

    def test_cnpj_invalido_e_erro(self, motor: Engine) -> None:
        with pytest.raises(RegraDeNegocio, match="CNPJ inválido"):
            ver_empresa(motor, agora=AGORA, cnpj="123")


class TestMudancasDesde:
    def test_lista_mudancas_de_todas_as_empresas_mais_recentes_primeiro(
        self, motor: Engine
    ) -> None:
        _gravar(motor, CNPJ, "2026-09-01 12:00:00", situacao="ATIVA")
        _gravar(motor, CNPJ, "2026-10-15 12:00:00", situacao="SUSPENSA")
        _gravar(motor, OUTRO_CNPJ, "2026-09-01 12:00:00", razao_social="OUTRA SA", porte="ME")
        _gravar(motor, OUTRO_CNPJ, ONTEM, razao_social="OUTRA SA", porte="EPP")

        resultado = mudancas_desde(motor, agora=AGORA, data="2026-10-01")

        assert [(m["cnpj"], m["campo"]) for m in resultado["mudancas"]] == [
            ("11.444.777/0001-61", "Porte"),
            ("11.222.333/0001-81", "Situação"),
        ]
        assert resultado["mudancas"][0]["razao_social"] == "OUTRA SA"

    def test_mudanca_antes_da_data_fica_de_fora(self, motor: Engine) -> None:
        _gravar(motor, CNPJ, "2026-08-01 12:00:00", situacao="ATIVA")
        _gravar(motor, CNPJ, "2026-09-01 12:00:00", situacao="BAIXADA")

        assert mudancas_desde(motor, agora=AGORA, data="2026-10-01")["mudancas"] == []

    def test_a_data_e_no_horario_de_brasilia(self, motor: Engine) -> None:
        # 02:00 UTC do dia 1º ainda é dia 30 em Brasília.
        _gravar(motor, CNPJ, "2026-09-01 12:00:00", situacao="ATIVA")
        _gravar(motor, CNPJ, "2026-10-01 02:00:00", situacao="BAIXADA")

        assert mudancas_desde(motor, agora=AGORA, data="2026-10-01")["mudancas"] == []

    def test_data_invalida_e_erro(self, motor: Engine) -> None:
        with pytest.raises(RegraDeNegocio, match="AAAA-MM-DD"):
            mudancas_desde(motor, agora=AGORA, data="01/10/2026")
