# Consulta de CNPJ com histórico

[![CI](https://github.com/SudoMary/consulta-cnpj/actions/workflows/ci.yml/badge.svg)](https://github.com/SudoMary/consulta-cnpj/actions/workflows/ci.yml)

> Recebe um CNPJ, busca os dados cadastrais em API pública, guarda cada consulta e mostra o que mudou entre elas.

## O problema

Antes de fechar contrato com um fornecedor, alguém precisa saber se a empresa existe, se está ativa, o porte, os sócios, em que ramo atua. Hoje isso é abrir o site da Receita, digitar captcha e copiar para um e-mail.

E o problema que ninguém resolve: a situação cadastral muda e ninguém percebe. A empresa estava **ATIVA** quando o contrato foi assinado em março e está **BAIXADA** em setembro. O pagamento continua saindo. Alguém descobre no fechamento do ano.

Consultar é fácil — existe API pública para isso. O que não existe pronto é guardar o que foi consultado e avisar quando mudou.

## Como funciona

```
 entradas      src/app.py         site (FastAPI + HTML montado no servidor, modo escuro)
               src/cli.py         linha de comando: consultar, acompanhar, perguntar
               src/coletor.py     coleta diária das empresas acompanhadas (GitHub Actions)
               src/assistente.py  perguntas em português, respondidas por um LLM
                   │
 regras        src/servico.py     valida o CNPJ, usa o cache, grava a observação, detecta mudança
                   │
 integração    src/cliente.py     timeout, novas tentativas com espera crescente, fonte reserva
               src/fontes/        um adaptador por API (BrasilAPI, Minha Receita), mesmo formato
                   │
 dados         src/repo.py        SQL escrito à mão, com parâmetros; a única camada que fala SQL
               src/db.py          SQLite no desenvolvimento, PostgreSQL (Supabase) em produção
```

Cada camada recebe de fora o que depende do mundo (banco, rede, relógio, API do modelo). Por isso os testes trocam a rede por uma falsa e rodam sem conexão, e a mesma regra serve ao site, à linha de comando e à coleta.

| Módulo | O que faz |
|---|---|
| `src/validacao.py` | Confere os dígitos verificadores do CNPJ antes de qualquer chamada externa. |
| `src/fontes/` | Busca na BrasilAPI e na Minha Receita e traduz as duas respostas para o mesmo formato. |
| `src/cliente.py` | Timeout, novas tentativas com espera crescente só para erro temporário (5xx, 429, rede), e a fonte reserva quando a primária falha. |
| `src/servico.py` | Cache de 24 horas, gravação append-only numa transação, detecção de mudança nos campos que importam e o painel das acompanhadas. |
| `src/repo.py` + `schema.sql` | Tabelas `empresa`, `observacao` (histórico, nunca alterado), `falha_coleta` e `pergunta`. O mesmo SQL roda nos dois bancos. |
| `src/coletor.py` | Recoleta diária idempotente: rodar duas vezes no mesmo dia não duplica nada. |
| `src/assistente.py` | Um LLM responde usando quatro ferramentas que só leem o banco: o Claude, com chave da Anthropic, ou um modelo grátis do OpenRouter. Limite diário e registro de tokens por pergunta. |
| `src/openrouter.py` | Cliente da API do OpenRouter: tenta de novo quando o modelo grátis está sobrecarregado no fornecedor e para na hora quando a cota do dia acaba. |
| `src/app.py`, `src/telas.py`, `src/formatacao.py` | Busca, ficha da empresa com linha do tempo das mudanças e painel das acompanhadas. |

**Stack:** Python 3.12, FastAPI e Jinja2 (HTML e CSS puros, sem framework de front), SQLAlchemy 2 com SQL escrito à mão, SQLite e PostgreSQL (Supabase), httpx, pydantic-settings, SDK da Anthropic ou API do OpenRouter com o modelo grátis Nemotron 3.5 Super, da NVIDIA (assistente), pytest (438 testes no CI, com os testes de banco nos dois bancos), ruff e GitHub Actions (CI e coleta agendada).

## Como rodar

**Estado:** consulta, histórico, detecção de mudança e coleta diária prontos, na tela web e na linha de comando; assistente de perguntas na linha de comando, com um modelo grátis. Falta o site no ar.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt

uvicorn src.app:app --reload                               # site em http://127.0.0.1:8000
python -m src.cli consultar 11.222.333/0001-81             # usa o cache de 24 horas
python -m src.cli consultar 11.222.333/0001-81 --forcar    # ignora o cache
python -m src.cli acompanhar 11.222.333/0001-81            # entra na coleta diária
python -m src.coletor                                      # roda a coleta diária
python -m src.cli perguntar "O que mudou este mês?"        # assistente (chave grátis do OpenRouter no .env)

pytest -q                                  # testes
ruff check . && ruff format --check .      # lint
```

## Publicação

O site roda no Render, plano grátis, a partir do [`render.yaml`](render.yaml): no painel do Render, New → Blueprint → este repositório. A única variável a preencher é `DATABASE_URL`, a connection string do Supabase no modo "Session pooler". O banco fica no Supabase porque o Render grátis apaga os arquivos quando o serviço dorme.

## Decisões de projeto

- **Append-only.** Cada consulta é uma observação nova; nunca `UPDATE` no registro anterior. A situação atual é estado derivado da observação mais recente. É o que permite responder *quando* a empresa mudou.
- **Cache de 24 horas.** Dado cadastral não muda de hora em hora; sem cache cada F5 vira chamada externa e a API pública corta por rate limit.
- **Duas fontes com fallback.** BrasilAPI como primária, Minha Receita como reserva. API pública cai; sem plano B o sistema cai junto.
- **Timeout + backoff + degradação.** Toda chamada externa tem timeout; erro de rede é tentado de novo com espera crescente; se tudo falhar e houver dado antigo, entrega o antigo com aviso em vez de tela de erro.
- **Coleta agendada no GitHub Actions.** Hospedagem gratuita hiberna; cron dentro dela não dispara. O histórico de execuções fica visível na aba Actions do repositório. A coleta é idempotente por dia: rodar duas vezes no mesmo dia não duplica observação. Para acompanhar uma empresa em produção: aba Actions → coleta → Run workflow, informando o CNPJ.
- **Assistente que só lê o banco.** Perguntas em português ("quais empresas mudaram este mês?") são respondidas por um LLM, que consulta o banco por ferramentas: listar as acompanhadas, buscar por nome, ver uma empresa e listar mudanças desde uma data. Nenhuma ferramenta chama a BrasilAPI ou grava dado, e o modelo responde só com o que elas devolveram. Cada pergunta fica registrada com os tokens gastos; um limite diário, o tamanho máximo da pergunta e o máximo de 6 chamadas por pergunta seguram o custo. O modelo é o Claude, com `ANTHROPIC_API_KEY`, ou um modelo grátis do OpenRouter, com `OPENROUTER_API_KEY` (grátis, 50 requisições por dia); as ferramentas são as mesmas e o código confere os parâmetros antes de rodar, porque nem toda API garante o esquema. Sem nenhuma das chaves, o assistente fica desligado e o resto funciona igual. Nos testes, as duas APIs são falsas: nenhum teste chama o modelo nem gasta dinheiro.
- **SQLite no desenvolvimento, PostgreSQL em produção.** A hospedagem gratuita apaga os arquivos locais ao hibernar, então o banco de produção fica no Supabase. O mesmo SQL roda nos dois: os testes passam sem conexão no SQLite, e o CI roda os testes de banco também num PostgreSQL de verdade.

## Limitações conhecidas (v1)

- Sem autenticação de usuário. Por isso qualquer visitante pode incluir empresas na coleta diária, até o limite de 20, que protege a cota das APIs públicas. Tirar uma empresa da coleta ainda não tem tela: é feito direto no banco.
- Sem consulta em lote.
- Sem integração com Portal da Transparência.
- Hospedagem gratuita hiberna: a primeira visita depois de um tempo ocioso pode levar cerca de 1 minuto (cold start).
- O assistente só existe na linha de comando. Com o modelo grátis do OpenRouter, foi testado de verdade (resposta certa em 2 chamadas, cerca de 12 s). Com o Claude, só com cliente falso e com o SDK real sobre rede simulada. O modelo grátis às vezes fica sobrecarregado no fornecedor: o sistema tenta de novo e, se não der, avisa.
- Em repositório público, o GitHub desativa agendamentos depois de 60 dias sem atividade no repositório. Se isso acontecer, a coleta diária precisa ser reativada na aba Actions.

## Licença

MIT — veja [LICENSE](LICENSE).
