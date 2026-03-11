CREATE (n:Document {
    name: $name,
    content: $content,
    rel_path: $rel_path,
    type: $type,
    fetched: true
})
