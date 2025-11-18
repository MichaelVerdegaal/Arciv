"""Semantic network construction using embeddings and graph-based analysis.

This module provides utilities for:
- Generating embeddings from text chunks
- Building semantic networks from embeddings
- Analyzing and exporting graph structures
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import networkx as nx
import torch
from semnet import SemanticNetwork, to_pandas
from sentence_transformers import SentenceTransformer


class GraphStats(TypedDict):
    """Statistics about a semantic network graph."""

    n_nodes: int
    n_edges: int
    n_components: int
    avg_degree: float


def get_device() -> str:
    """Get the best available device for PyTorch operations.

    Returns:
        "cuda" if GPU is available, otherwise "cpu"
    """
    return "cuda" if torch.cuda.is_available() else "cpu"


def generate_embeddings(
    texts: Sequence[str],
    model_name: str = "Qwen/Qwen3-Embedding-0.6B",
    batch_size: int = 32,
    device: str | None = None,
) -> Any:
    """Generate embeddings for a sequence of texts.

    Args:
        texts: List of text strings to embed
        model_name: HuggingFace model name for embeddings
        batch_size: Number of texts to process in each batch
        device: Device to use ("cuda" or "cpu"). If None, auto-detected.

    Returns:
        Numpy array of embeddings, shape (n_texts, embedding_dim)

    Example:
        >>> texts = ["First document", "Second document"]
        >>> embeddings = generate_embeddings(texts, batch_size=2)
    """
    if device is None:
        device = get_device()

    embedding_model = SentenceTransformer(model_name, device=device)

    embeddings = embedding_model.encode(  # type: ignore[call-overload]
        texts,
        batch_size=batch_size,
        show_progress_bar=True
    )

    return embeddings


def build_semantic_graph(
    embeddings: Any,
    labels: Sequence[str],
    threshold: float = 0.3,
) -> nx.Graph:
    """Build a semantic network graph from embeddings.

    Creates a graph where nodes represent text chunks and edges represent
    semantic similarity above the threshold.

    Args:
        embeddings: Array of embeddings, shape (n_items, embedding_dim)
        labels: Labels for each embedding (e.g., original text)
        threshold: Similarity threshold for creating edges (0.0-1.0)

    Returns:
        NetworkX graph with nodes and weighted edges

    Raises:
        ValueError: If embeddings and labels have different lengths

    Example:
        >>> embeddings = generate_embeddings(["text1", "text2"])
        >>> graph = build_semantic_graph(embeddings, ["text1", "text2"])
    """
    if len(embeddings) != len(labels):
        raise ValueError(
            f"Embeddings and labels must have same length. "
            f"Got {len(embeddings)} embeddings and {len(labels)} labels."
        )

    sem = SemanticNetwork(thresh=threshold)
    graph = sem.fit_transform(embeddings, labels=list(labels))

    return graph


def analyze_graph(graph: nx.Graph) -> GraphStats:
    """Analyze a semantic network graph and return statistics.

    Args:
        graph: NetworkX graph to analyze

    Returns:
        Dictionary containing graph statistics
    """
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    n_components = nx.number_connected_components(graph)

    # Calculate average degree
    degrees = [d for _, d in graph.degree()]
    avg_degree = sum(degrees) / len(degrees) if degrees else 0.0

    stats: GraphStats = {
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "n_components": n_components,
        "avg_degree": avg_degree,
    }

    return stats


def export_graph_to_csv(
    graph: nx.Graph,
    output_dir: Path,
    nodes_filename: str = "nodes.csv",
    edges_filename: str = "edges.csv",
) -> tuple[Path, Path]:
    """Export a NetworkX graph to CSV files.

    Args:
        graph: NetworkX graph to export
        output_dir: Directory to save CSV files
        nodes_filename: Filename for nodes CSV
        edges_filename: Filename for edges CSV

    Returns:
        Tuple of (nodes_path, edges_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = output_dir / nodes_filename
    edges_path = output_dir / edges_filename

    nodes_df, edges_df = to_pandas(graph)

    nodes_df.to_csv(nodes_path, index=False)
    edges_df.to_csv(edges_path, index=False)

    return nodes_path, edges_path
