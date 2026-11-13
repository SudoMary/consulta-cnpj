# Consulta de CNPJ com histórico

[![CI](https://github.com/SudoMary/consulta-cnpj/actions/workflows/ci.yml/badge.svg)](https://github.com/SudoMary/consulta-cnpj/actions/workflows/ci.yml)

> Recebe um CNPJ, busca os dados cadastrais em API pública, guarda cada consulta e mostra o que mudou entre elas.

## O problema

Antes de fechar contrato com um fornecedor, alguém precisa saber se a empresa existe, se está ativa, o porte, os sócios, em que ramo atua. Hoje isso é abrir o site da Receita, digitar captcha e copiar para um e-mail.

E o problema que ninguém resolve: a situação cadastral muda e ninguém percebe. A empresa estava **ATIVA** quando o contrato foi assinado em março e está **BAIXADA** em setembro. O pagamento continua saindo. Alguém descobre no fechamento do ano.

Consultar é fácil — existe API pública para isso. O que não existe pronto é guardar o que foi consultado e avisar quando mudou.

## Como rodar

**Estado:** consulta, histórico, detecção de mudança e coleta diária prontos, na tela web e na linha de comando. Falta o site no ar.

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
python -m src.cli perguntar "O que mudou este mês?"        # assistente (precisa de chave)

pytest -q                                  # testes
ruff check . && ruff format --check .      # lint
```

## Decisões de projeto

- **Append-only.** Cada consulta é uma observação nova; nunca `UPDATE` no registro anterior. A situação atual é estado derivado da observação mais recente. É o que permite responder *quando* a empresa mudou.
- **Cache de 24 horas.** Dado cadastral não muda de hora em hora; sem cache cada F5 vira chamada externa e a API pública corta por rate limit.
- **Duas fontes com fallback.** BrasilAPI como primária, Minha Receita como reserva. API pública cai; sem plano B o sistema cai junto.
- **Timeout + backoff + degradação.** Toda chamada externa tem timeout; erro de rede é tentado de novo com espera crescente; se tudo falhar e houver dado antigo, entrega o antigo com aviso em vez de tela de erro.
- **Coleta agendada no GitHub Actions.** Hospedagem gratuita hiberna; cron dentro dela não dispara. O histórico de execuções fica visível na aba Actions do repositório. A coleta é idempotente por dia: rodar duas vezes no mesmo dia não duplica observação. Para acompanhar uma empresa em produção: aba Actions → coleta → Run workflow, informando o CNPJ.
- **Assistente que só lê o banco.** Perguntas em português ("quais empresas mudaram este mês?") são respondidas pelo Claude, que consulta o banco por ferramentas: listar as acompanhadas, buscar por nome, ver uma empresa e listar mudanças desde uma data. Nenhuma ferramenta chama a BrasilAPI ou grava dado, e o modelo responde só com o que elas devolveram. Cada pergunta fica registrada com os tokens gastos; um limite diário, o tamanho máximo da pergunta e o máximo de 6 chamadas por pergunta seguram o custo. Sem `ANTHROPIC_API_KEY`, o assistente fica desligado e o resto funciona igual. Nos testes, a API é um cliente falso: nenhum teste chama o modelo nem gasta dinheiro.
- **SQLite no desenvolvimento, PostgreSQL em produção.** A hospedagem gratuita apaga os arquivos locais ao hibernar, então o banco de produção fica no Supabase. O mesmo SQL roda nos dois: os testes passam sem conexão no SQLite, e o CI roda os testes de banco também num PostgreSQL de verdade.

## Limitações conhecidas (v1)

- Sem autenticação de usuário. Por isso qualquer visitante pode incluir empresas na coleta diária, até o limite de 20, que protege a cota das APIs públicas. Tirar uma empresa da coleta ainda não tem tela: é feito direto no banco.
- Sem consulta em lote.
- Sem integração com Portal da Transparência.
- Hospedagem gratuita hiberna: a primeira visita depois de um tempo ocioso pode levar cerca de 1 minuto (cold start).
- Em repositório público, o GitHub desativa agendamentos depois de 60 dias sem atividade no repositório. Se isso acontecer, a coleta diária precisa ser reativada na aba Actions.

## Licença

MIT — veja [LICENSE](LICENSE).
