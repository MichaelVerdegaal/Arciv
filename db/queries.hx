// Create Document Node
QUERY createDocument(filename: String, file_created_at: Date, file_modified_at: Date, content: String) =>
    document <- AddN<Document>({
        filename: filename,
        file_created_at: file_created_at,
        file_modified_at: file_modified_at,
        content: content
    })
    RETURN document

// Create Category Node
QUERY createCategory(name: String) =>
    category <- AddN<Category>({
        name: name
    })
    RETURN category

// Link Document to Category
QUERY linkDocumentToCategory(document_id: ID, category_id: ID) =>
    document <- N<Document>(document_id)
    category <- N<Category>(category_id)
    edge <- AddE<HasCategory>::From(document)::To(category)
    RETURN edge