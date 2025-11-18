"""Document processing and chunking for Obsidian notes.

This module provides utilities for:
- Preprocessing Obsidian markdown notes (removing frontmatter, metadata)
- Chunking notes using Chonkie's Pipeline API
- Generating structured chunks suitable for graph construction
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from chonkie import Pipeline
from transformers import PreTrainedTokenizerFast

from clotho.config import NOTE_PATH


def get_note_files() -> list[Path]:
    """Get all markdown files in the NOTE_PATH directory.
    
    Returns:
        List of paths to markdown files found recursively
    """
    return list(NOTE_PATH.glob("**/*.md"))


def preprocess_note_content(content: str) -> str:
    """Remove YAML frontmatter and content before first H1 header.
    
    Obsidian notes often have YAML frontmatter and metadata at the top.
    We only want the actual content starting from the first H1 header.
    
    Args:
        content: Raw note content with potential frontmatter
        
    Returns:
        Cleaned content starting from first H1 header
        
    Example:
        >>> content = "---\\ndate: 2024-03-15\\n---\\n\\nSome text\\n# Heading\\nContent"
        >>> preprocess_note_content(content)
        '# Heading\\nContent'
    """
    # Remove YAML frontmatter (--- at start, anything until next ---)
    content = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)
    
    # Find first H1 header (# Heading)
    h1_match = re.search(r"^#\s+.+$", content, flags=re.MULTILINE)
    
    if h1_match:
        # Return content starting from first H1
        return content[h1_match.start() :]
    
    # If no H1 found, return content without frontmatter
    return content.strip()


def chunk_notes(
    note_files: Sequence[Path],
    tokenizer: PreTrainedTokenizerFast,
    *,
    initial_chunk_size: int = 512,
    semantic_chunk_size: int = 256,
    overlap_context_size: int = 32,
) -> list[dict[str, Any]]:
    """Chunk markdown files using sophisticated Chonkie Pipeline.
    
    Uses a multi-stage chunking strategy:
    1. Recursive chunking respecting markdown structure (headers, lists, etc.)
    2. Semantic chunking to split by topic coherence
    3. Overlap refinement to preserve context across chunks
    
    Args:
        note_files: List of paths to markdown files
        tokenizer: HuggingFace tokenizer instance for token counting
        initial_chunk_size: Initial chunk size for recursive chunker (respects markdown)
        semantic_chunk_size: Target size for semantic similarity-based splitting
        overlap_context_size: Number of tokens to overlap between chunks
        
    Returns:
        List of dicts with keys:
        - text: Chunk text content
        - source_file: Path to original note file
        - token_count: Number of tokens in chunk
        - start_index: Start position in preprocessed text
        - end_index: End position in preprocessed text
        - chunk_id: Unique identifier (filename_chunkindex)
        
    Example:
        >>> from transformers import AutoTokenizer
        >>> tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-0.6B")
        >>> files = [Path("note1.md"), Path("note2.md")]
        >>> chunks = chunk_notes(files, tokenizer)
    """
    # Build sophisticated chunking pipeline
    pipeline = (
        Pipeline()
        .chunk_with(
            "recursive",
            tokenizer=tokenizer,
            chunk_size=initial_chunk_size,
            recipe="markdown",  # Respect markdown structure
        )
        .chunk_with(
            "semantic",  # Further split by semantic similarity
            chunk_size=semantic_chunk_size,
        )
        .refine_with(
            "overlap",  # Add overlapping context
            context_size=overlap_context_size,
        )
    )
    
    all_chunks: list[dict[str, Any]] = []
    
    for note_file in note_files:
        with open(note_file, encoding="utf-8") as f:
            raw_content = f.read()
        
        # Preprocess to remove frontmatter and metadata
        cleaned_content = preprocess_note_content(raw_content)
        
        if not cleaned_content.strip():
            # Skip empty notes
            continue
        
        # Process with pipeline (single text returns Document, not list)
        doc = pipeline.run(texts=cleaned_content)
        
        # Convert to our chunk format
        for idx, chunk in enumerate(doc.chunks):  # type: ignore[union-attr]
            all_chunks.append({
                "text": chunk.text,
                "source_file": str(note_file),
                "token_count": chunk.token_count,
                "start_index": chunk.start_index,
                "end_index": chunk.end_index,
                "chunk_id": f"{note_file.stem}_{idx}",
            })
    
    return all_chunks
