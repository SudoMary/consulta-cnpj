# Consulta de CNPJ com histórico

> Recebe um CNPJ, busca os dados cadastrais em API pública, guarda cada consulta e mostra o que mudou entre elas.

## O problema

Antes de fechar contrato com um fornecedor, alguém precisa saber se a empresa existe, se está ativa, o porte, os sócios, em que ramo atua. Hoje isso é abrir o site da Receita, digitar captcha e copiar para um e-mail.

E o problema que ninguém resolve: a situação cadastral muda e ninguém percebe. A empresa estava **ATIVA** quando o contrato foi assinado em março e está **BAIXADA** em setembro. O pagamento continua saindo. Alguém descobre no fechamento do ano.

Consultar é fácil — existe API pública para isso. O que não existe pronto é guardar o que foi consultado e avisar quando mudou.

## Como rodar

> **Em construção.** Primeira entrega (validador de CNPJ) ainda não implementada. Este README será atualizado em cada entrega.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt
```

## Decisões de projeto

- **Append-only.** Cada consulta é uma observação nova; nunca `UPDATE` no registro anterior. A situação atual é estado derivado da observação mais recente. É o que permite responder *quando* a empresa mudou.
- **Cache de 24 horas.** Dado cadastral não muda de hora em hora; sem cache cada F5 vira chamada externa e a API pública corta por rate limit.
- **Duas fontes com fallback.** BrasilAPI como primária, Minha Receita como reserva. API pública cai; sem plano B o sistema cai junto.
- **Timeout + backoff + degradação.** Toda chamada externa tem timeout; erro de rede é tentado de novo com espera crescente; se tudo falhar e houver dado antigo, entrega o antigo com aviso em vez de tela de erro.
- **Coleta agendada no GitHub Actions.** Hospedagem gratuita hiberna; cron dentro dela não dispara. O histórico de execuções fica visível na aba Actions do repositório.

## Limitações conhecidas (v1)

- Sem autenticação de usuário.
- Sem consulta em lote.
- Sem integração com Portal da Transparência.
- Hospedagem gratuita hiberna: a primeira visita depois de um tempo ocioso pode levar ~30s (cold start).

## Licença

MIT — veja [LICENSE](LICENSE).
