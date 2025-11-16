QUERY CreateNote(filename: String, created_at: Date, updated_at: Date) =>
    note <- AddN<Note>({
        filename: filename,
        created_at: created_at,
        updated_at: updated_at
    })
    RETURN note
