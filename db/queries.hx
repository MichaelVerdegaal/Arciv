QUERY CreateDocument(filename: String, file_created_at: Date, file_modified_at: Date, content: String) =>
    document <- AddN<Document>({
        filename: filename,
        file_created_at: file_created_at,
        file_modified_at: file_modified_at,
        content: content
    })
    RETURN document
