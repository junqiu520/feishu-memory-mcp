CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    preview TEXT,
    text TEXT,
    content_hash TEXT,
    content_ref_type TEXT,
    content_ref_token TEXT,
    content_ref_url TEXT,
    file_ref_json TEXT,
    tags_json TEXT,
    source_user TEXT,
    source_agent TEXT,
    origin TEXT,
    extra_json TEXT,
    text_empty INTEGER DEFAULT 0,
    embedding_status TEXT,
    sync_status TEXT,
    last_attempt_at INTEGER,
    token_count INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_source_agent ON records(source_agent);
CREATE INDEX IF NOT EXISTS idx_records_updated_at ON records(updated_at);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
CREATE INDEX IF NOT EXISTS idx_records_content_hash ON records(content_hash);

CREATE TABLE IF NOT EXISTS record_tags (
    record_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (record_id, tag),
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_record_tags_tag ON record_tags(tag);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_sync_at INTEGER,
    last_full_sync_at INTEGER,
    last_rebuild_at INTEGER,
    bitable_schema_hash TEXT,
    local_instance_id TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    text,
    title,
    preview,
    tags,
    content='records',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
    INSERT INTO records_fts(rowid, text, title, preview, tags)
    VALUES (new.rowid, new.text, new.title, new.preview,
            COALESCE(new.tags_json, ''));
END;

CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, text, title, preview, tags)
    VALUES ('delete', old.rowid, old.text, old.title, old.preview,
            COALESCE(old.tags_json, ''));
END;

CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, text, title, preview, tags)
    VALUES ('delete', old.rowid, old.text, old.title, old.preview,
            COALESCE(old.tags_json, ''));
    INSERT INTO records_fts(rowid, text, title, preview, tags)
    VALUES (new.rowid, new.text, new.title, new.preview,
            COALESCE(new.tags_json, ''));
END;
