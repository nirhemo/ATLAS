-- ============================================================================
-- ATLAS · L2 Memory · SQLite + sqlite-vec schema (v1.0.0)
-- ----------------------------------------------------------------------------
-- The vault (markdown notes in atlas/memory/vault/) is the SOURCE OF TRUTH.
-- This database is a derived INDEX over the vault plus episodic bookkeeping.
-- It can be deleted and rebuilt from the vault + episodic JSONL at any time.
--
-- Engine: SQLite with the sqlite-vec extension for vector search.
-- (LanceDB is an acceptable drop-in alternative; the contract is the same:
--  embed note chunks, search by cosine similarity, return note paths.)
-- ============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- --------------------------------------------------------------------------
-- notes: one row per vault note (one markdown file). Mirrors YAML frontmatter.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY,
    path            TEXT    NOT NULL UNIQUE,      -- e.g. 'people/nir.md'
    title           TEXT    NOT NULL,
    type            TEXT    NOT NULL,             -- person|project|preference|decision|topic
    created         TEXT    NOT NULL,             -- ISO-8601
    updated         TEXT    NOT NULL,             -- ISO-8601
    confidence      REAL    NOT NULL DEFAULT 0.8, -- 0.0–1.0, decayed not deleted
    owner_edited    INTEGER NOT NULL DEFAULT 0,   -- 1 = manually edited, never overwrite
    content_hash    TEXT    NOT NULL,             -- detect changes for incremental reindex
    body            TEXT    NOT NULL              -- full markdown body cache
);

CREATE INDEX IF NOT EXISTS idx_notes_type   ON notes(type);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated);

-- --------------------------------------------------------------------------
-- links: the [[wiki-link]] knowledge graph between notes.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS links (
    src_note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    dst_title       TEXT    NOT NULL,             -- target by title (may be unresolved)
    dst_note_id     INTEGER REFERENCES notes(id) ON DELETE SET NULL,
    PRIMARY KEY (src_note_id, dst_title)
);

-- --------------------------------------------------------------------------
-- chunks: notes split into retrievable passages, each embedded.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY,
    note_id         INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,             -- position within the note
    text            TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_note ON chunks(note_id);

-- --------------------------------------------------------------------------
-- vec_chunks: the vector index (sqlite-vec virtual table).
-- Dimension MUST match the embedding model in vector_store.config.json.
-- Default: 384 dims (bge-small / all-MiniLM-L6-v2 class local model).
-- --------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id        INTEGER PRIMARY KEY,
    embedding       FLOAT[384]
);

-- --------------------------------------------------------------------------
-- episodic_index: pointers into append-only JSONL transcripts (cold storage).
-- Transcripts are NOT notes. This table lets consolidation and back-pointers
-- find the source line a vault fact was distilled from.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS episodic_index (
    id              INTEGER PRIMARY KEY,
    file            TEXT    NOT NULL,             -- e.g. 'episodic/2026-06-12.jsonl'
    line            INTEGER NOT NULL,             -- line number within the file
    ts              TEXT    NOT NULL,             -- ISO-8601 of the utterance
    role            TEXT    NOT NULL,             -- owner|atlas|system
    consolidated    INTEGER NOT NULL DEFAULT 0,  -- 1 = already distilled into vault
    UNIQUE(file, line)
);

CREATE INDEX IF NOT EXISTS idx_episodic_unconsolidated
    ON episodic_index(consolidated) WHERE consolidated = 0;

-- --------------------------------------------------------------------------
-- backrefs: note fact -> source transcript line (auditability / R2 reversibility)
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backrefs (
    note_id         INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    episodic_id     INTEGER NOT NULL REFERENCES episodic_index(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, episodic_id)
);

-- --------------------------------------------------------------------------
-- consolidation_runs: audit log of nightly sleep-time passes.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consolidation_runs (
    id              INTEGER PRIMARY KEY,
    started         TEXT    NOT NULL,
    finished        TEXT,
    notes_created   INTEGER NOT NULL DEFAULT 0,
    notes_updated   INTEGER NOT NULL DEFAULT 0,
    lines_processed INTEGER NOT NULL DEFAULT 0,
    git_commit      TEXT,                          -- vault commit hash after run
    status          TEXT    NOT NULL DEFAULT 'running'  -- running|ok|rolled_back
);
