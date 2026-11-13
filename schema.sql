-- Esquema do banco do Projeto A: Consulta de CNPJ com histórico.
--
-- Aplicado ao abrir o banco (ver src/db.py). Roda igual no SQLite
-- (desenvolvimento e testes) e no PostgreSQL (producao). A unica diferenca,
-- o tipo da coluna `id`, e preenchida por src/db.py.
--
-- Todas as tabelas e indices usam IF NOT EXISTS: rodar duas vezes no mesmo
-- banco tem o mesmo efeito que rodar uma. Isso e o que chamamos de idempotente.
--
-- PRAGMA foreign_keys = ON deve ser aplicado em TODA conexao do SQLite (ele
-- ignora FK por padrao). Fica em src/db.py, nao aqui.

-- ---------------------------------------------------------------------
-- empresa: cada CNPJ consultado ao menos uma vez.
--
-- NAO tem coluna `situacao` de proposito: a situacao atual e estado
-- derivado da observacao mais recente (append-only).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS empresa (
    -- 14 digitos, sem mascara. TEXT e nao INTEGER: CNPJ pode comecar com 0.
    cnpj              TEXT    PRIMARY KEY CHECK (length(cnpj) = 14),
    -- ISO 'YYYY-MM-DD HH:MM:SS', sempre em UTC; nesse formato, TEXT ordena como data.
    primeira_consulta TEXT    NOT NULL,
    ultima_consulta   TEXT    NOT NULL,
    -- 1 = recoleta diaria; 0 = so o que ja foi consultado.
    acompanhando      INTEGER NOT NULL DEFAULT 0 CHECK (acompanhando IN (0, 1))
);

-- ---------------------------------------------------------------------
-- observacao: historico append-only de cada consulta.
--
-- Cada linha e um snapshot do retorno da API naquele instante. NUNCA ha
-- UPDATE nem DELETE aqui — comparar linhas consecutivas e o que permite
-- responder "mudou quando".
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observacao (
    id               CHAVE_SUBSTITUTA,
    cnpj             TEXT    NOT NULL REFERENCES empresa(cnpj),
    coletado_em      TEXT    NOT NULL,             -- ISO 'YYYY-MM-DD HH:MM:SS'
    fonte            TEXT    NOT NULL CHECK (fonte IN ('brasilapi', 'minhareceita')),

    -- Campos extraidos do JSON de retorno (nulos quando a fonte nao trouxe).
    razao_social     TEXT,
    nome_fantasia    TEXT,
    situacao         TEXT,
    data_situacao    TEXT,
    porte            TEXT,
    cnae_codigo      TEXT,
    cnae_descricao   TEXT,
    municipio        TEXT,
    uf               TEXT,
    -- Dinheiro em centavos, nunca float. BIGINT: o capital da Petrobras em
    -- centavos nao cabe no INTEGER de 32 bits do PostgreSQL.
    capital_centavos BIGINT,
    qtd_socios       INTEGER,

    -- A resposta inteira como veio da fonte. E o que salva o retrabalho
    -- quando, no futuro, voce quiser um campo que nao extraiu hoje.
    bruto_json       TEXT    NOT NULL
);

-- Toda consulta do sistema e "observacoes desta empresa, em ordem de data".
CREATE INDEX IF NOT EXISTS idx_obs_cnpj ON observacao(cnpj, coletado_em);

-- ---------------------------------------------------------------------
-- falha_coleta: toda falha de tentativa de busca, para observabilidade.
--
-- NAO tem REFERENCES empresa(cnpj): a falha pode ocorrer antes da empresa
-- existir no banco (CNPJ valido, mas fonte fora do ar antes do primeiro
-- registro bem-sucedido).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS falha_coleta (
    id          CHAVE_SUBSTITUTA,
    cnpj        TEXT NOT NULL,
    ocorrido_em TEXT NOT NULL,                     -- ISO 'YYYY-MM-DD HH:MM:SS'
    fonte       TEXT NOT NULL,
    motivo      TEXT NOT NULL                      -- mensagem legivel (timeout, HTTP 500, etc.)
);

-- ---------------------------------------------------------------------
-- pergunta: cada pergunta feita ao assistente, para medir uso e custo.
--
-- O limite diario de perguntas conta as linhas daqui. O texto fica guardado
-- para avaliar as respostas depois; a resposta nao e guardada.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pergunta (
    id             CHAVE_SUBSTITUTA,
    feita_em       TEXT    NOT NULL,               -- ISO 'YYYY-MM-DD HH:MM:SS', UTC
    texto          TEXT    NOT NULL,
    modelo         TEXT    NOT NULL,
    desfecho       TEXT    NOT NULL
        CHECK (desfecho IN ('respondida', 'recusada', 'sem_conclusao', 'erro')),
    chamadas       INTEGER NOT NULL,               -- chamadas ao modelo nesta pergunta
    tokens_entrada BIGINT  NOT NULL,
    tokens_saida   BIGINT  NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pergunta_feita_em ON pergunta(feita_em);
