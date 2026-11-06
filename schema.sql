-- Esquema do banco do Projeto A: Consulta de CNPJ com histórico.
--
-- Aplicado na primeira conexão (ver src/db.py). Todas as tabelas e indices
-- usam IF NOT EXISTS: rodar duas vezes no mesmo banco tem o mesmo efeito
-- que rodar uma. Isso e o que chamamos de idempotente.
--
-- PRAGMA foreign_keys = ON deve ser aplicado em TODA conexao (o SQLite
-- ignora FK por padrao). Fica em src/db.py, nao aqui.

-- ---------------------------------------------------------------------
-- empresa: cada CNPJ consultado ao menos uma vez.
--
-- NAO tem coluna `situacao` de proposito: a situacao atual e estado
-- derivado da observacao mais recente (decisao append-only em
-- vault/Decisoes/Consultas append-only.md).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS empresa (
    -- 14 digitos, sem mascara. TEXT e nao INTEGER: CNPJ pode comecar com 0.
    cnpj              TEXT    PRIMARY KEY CHECK (length(cnpj) = 14),
    -- ISO 'YYYY-MM-DD HH:MM:SS'; TEXT ordena bem e nao perde fuso.
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
    id               INTEGER PRIMARY KEY,
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
    capital_centavos INTEGER,                      -- dinheiro em centavos, nunca float
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
    id          INTEGER PRIMARY KEY,
    cnpj        TEXT NOT NULL,
    ocorrido_em TEXT NOT NULL,                     -- ISO 'YYYY-MM-DD HH:MM:SS'
    fonte       TEXT NOT NULL,
    motivo      TEXT NOT NULL                      -- mensagem legivel (timeout, HTTP 500, etc.)
);
