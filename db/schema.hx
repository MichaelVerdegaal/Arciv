// NODES //
N::Document {
    filename: String,
    file_created_at: Date,
    file_modified_at: Date,
    node_created_at: Date DEFAULT NOW,
    node_updated_at: Date DEFAULT NOW,
    content: String,
}

N::Category {
    name: String
}

// EDGES //
E::HasCategory {
    From: Document,
    To: Category
}