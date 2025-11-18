"""Experiment: Build semantic network from Obsidian notes.

This script demonstrates the complete pipeline:
1. Load and preprocess daily notes
2. Chunk using sophisticated markdown-aware strategy
3. Generate embeddings
4. Build semantic graph
5. Analyze and export
"""

from collections import Counter
import random

import networkx as nx
from loguru import logger
from transformers import AutoTokenizer

from clotho.documents import chunk_notes, get_note_files
from clotho.semantic_network import (
    analyze_graph,
    build_semantic_graph,
    export_graph_to_csv,
    generate_embeddings,
    get_device,
)
from pathlib import Path

# Configure logging
logger.info(f"Using device: {get_device()}")

# ================
# Step 1: Load notes
# ================
note_files = get_note_files()
logger.info(f"Found {len(note_files)} note files")

# ================
# Step 2: Chunk documents with sophisticated pipeline
# ================
logger.info("Chunking documents with markdown-aware pipeline...")
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-0.6B")

chunks = chunk_notes(
    note_files,
    tokenizer,
)

docs = [chunk["text"] for chunk in chunks]
logger.info(f"Created {len(chunks)} chunks from {len(note_files)} documents")

# ================
# Step 3: Generate embeddings
# ================
logger.info("Generating embeddings...")
embeddings = generate_embeddings(
    docs,
    model_name="Qwen/Qwen3-Embedding-0.6B",
    batch_size=32,
)

logger.info(f"Generated embeddings with shape: {embeddings.shape}")

# ================
# Step 4: Build semantic graph
# ================
logger.info("Building semantic network...")
G = build_semantic_graph(
    embeddings,
    labels=docs,
    threshold=0.3,  # Similarity threshold for edges
)

# ================
# Step 5: Analyze graph
# ================
logger.info("Analyzing graph structure...")
stats = analyze_graph(G)

logger.info(
    "Graph statistics",
    extra={
        "nodes": stats["n_nodes"],
        "edges": stats["n_edges"],
        "components": stats["n_components"],
        "avg_degree": f"{stats['avg_degree']:.2f}",
    },
)

# ================
# Step 6: Export to CSV
# ================
output_dir = Path("data/output")
nodes_path, edges_path = export_graph_to_csv(G, output_dir)
logger.info(f"Exported graph to {nodes_path} and {edges_path}")


# ================
random.seed(123)

# Take a random sample
print("\nSample nodes:")
sample = random.sample(list(G.nodes(data=True)), min(5, G.number_of_nodes()))

# Print node index and text preview
for idx, node in sample:
    label = node.get("label", "")
    print(f'Node {idx}: "{label[:50]}..."')


print("\nSample edges:")

# Take a random sample
random.seed(123)
sample = random.sample(list(G.edges(data=True)), min(5, G.number_of_edges()))

# Order by weight
for u, v, edge in sorted(sample, key=lambda x: x[2]["weight"], reverse=True):
    quote_u = G.nodes[u].get("label", "")[:30]
    quote_v = G.nodes[v].get("label", "")[:30]
    print(f'"{quote_u}..." -- {edge["weight"]:.2f} -- "{quote_v}..."')

# Get connected components
components = list(nx.connected_components(G))
print(f"\nThe graph has {len(components)} connected components.")

# Count how many components of each size there are
component_sizes = [len(c) for c in components]
component_size_counts = Counter(component_sizes)

for size, count in sorted(component_size_counts.items(), reverse=True):
    print(f"Size {size}: {count} components")
