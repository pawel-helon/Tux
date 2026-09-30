CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS threads, requests, responses, memories;

CREATE TABLE threads (
    id                BIGSERIAL PRIMARY KEY,
    ppid              BIGINT NOT NULL UNIQUE,
    shell_start       TEXT,
    title             TEXT,
    summary           TEXT,
    summary_embedding vector(768),
    created_at        DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at        DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE requests (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(768),
    created_at  DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at  DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE responses (
    id          BIGSERIAL PRIMARY KEY,
    request_id  BIGINT NOT NULL UNIQUE REFERENCES requests(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(768),
    created_at  DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at  DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE INDEX requests_thread_id_idx
    ON requests(thread_id);

CREATE INDEX threads_summary_embedding_hnsw_idx
    ON threads
    USING hnsw (summary_embedding vector_cosine_ops);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON threads, requests, responses
    TO tux;

GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA public
    TO tux;
