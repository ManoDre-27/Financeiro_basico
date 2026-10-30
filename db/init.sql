-- Inicializacao do PostgreSQL para o Terminal de Inteligencia Global.
-- Executado automaticamente pelo container na primeira criacao do volume.
-- Ativa TimescaleDB (series temporais) e pgvector (pesquisa semantica),
-- conforme a seccao 3 do documento de produto.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

-- As tabelas sao criadas pela aplicacao (SQLAlchemy). Depois de existirem,
-- a tabela de precos pode ser convertida em hypertable Timescale, ex:
--   SELECT create_hypertable('prices', 'ts', if_not_exists => TRUE);
