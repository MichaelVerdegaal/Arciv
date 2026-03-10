CREATE NODE TABLE IF NOT EXISTS Source (
    name STRING PRIMARY KEY,
    uri STRING,
    created_at TIMESTAMP DEFAULT current_timestamp()
)
