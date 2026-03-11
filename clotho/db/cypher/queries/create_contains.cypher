MATCH (s:Source {name: $source_name}), (d:Document {name: $doc_name})
CREATE (s)-[:Contains]->(d)
