CREATE NODE TABLE IF NOT EXISTS Document (
    name STRING PRIMARY KEY,
    content STRING,
    rel_path STRING,
    type STRING,
    fetched BOOLEAN DEFAULT false,
    explored BOOLEAN DEFAULT false,
    level INT16 DEFAULT 0,
    created_at TIMESTAMP DEFAULT current_timestamp()
)
