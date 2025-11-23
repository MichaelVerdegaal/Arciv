from pathlib import Path
from datetime import datetime, timezone
import re
from collections.abc import Sequence
from typing import Any
from chonkie import Pipeline
from transformers import PreTrainedTokenizerFast
from warnings import deprecated


def get_note_files(note_dir: Path) -> list[Path]:
    """Get all markdown files in the NOTE_PATH directory.

    Returns:
        List of paths to markdown files found recursively
    """
    return list(note_dir.glob("**/*.md"))


def process_note_content(content: str) -> str:
    """Remove metadata headers and content before first H1 header.

    Handles both traditional YAML frontmatter (---...---) and
    timestamp/status patterns found in Obsidian daily notes.

    Args:
        content: Raw note content with potential frontmatter

    Returns:
        Cleaned content starting from first H1 header
    """
    # Remove traditional YAML frontmatter (--- at start, anything until next ---)
    content = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)

    # Remove timestamp pattern (e.g., "20251121 1011") and Status line
    # This handles lines like "20241101 1111" followed by "Status: #daily"
    content = re.sub(
        r"^\d{8}\s+\d{4}\s*\n\s*Status:\s*#\w+\s*\n", "", content, flags=re.MULTILINE
    )

    # Find first H1 header (# Heading)
    h1_match = re.search(r"^#\s+.+$", content, flags=re.MULTILINE)

    if h1_match:
        # Return content starting from first H1, stripped of leading/trailing whitespace
        return content[h1_match.start() :].strip()

    # If no H1 found, return cleaned content
    return content.strip()


def file_created_date(path: Path) -> datetime:
    """Get the file creation date as a datetime object.

    Args:
        path: Path to the file

    Returns:
        Datetime object representing the file creation date
    """
    created_date = datetime.fromtimestamp(path.stat().st_ctime, tz=timezone.utc)
    created_date_iso = created_date.isoformat()
    return created_date_iso


def file_modified_date(path: Path) -> datetime:
    """Get the file modification date as a datetime object.

    Args:
        path: Path to the file

    Returns:
        Datetime object representing the file modification date
    """
    modified_date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    modified_date_iso = modified_date.isoformat()
    return modified_date_iso


def get_note_info(note: Path) -> dict[str, str | datetime]:
    """Returns a dictionary with file metadata for the given note.

    The creation and modification dates are returned as RFC3339 strings.

    Args:
        - note: Path to the note file

    Returns:
        - Dictionary with keys: filename, creation_date, modification_date
    """
    filename = note.name
    creation_date = file_created_date(note)
    modification_date = file_modified_date(note)
    note_content = note.read_text(encoding="utf-8")
    note_content_processed = process_note_content(note_content)

    metadata = {
        "filename": filename,
        "content": note_content_processed,
        "creation_date": creation_date,
        "modification_date": modification_date,
    }
    return metadata


@deprecated("Going to remove this in favor of Helix's built-in chunking.")
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
        cleaned_content = process_note_content(raw_content)

        if not cleaned_content.strip():
            # Skip empty notes
            continue

        # Process with pipeline (single text returns Document, not list)
        doc = pipeline.run(texts=cleaned_content)

        # Convert to our chunk format
        for idx, chunk in enumerate(doc.chunks):  # type: ignore[union-attr]
            all_chunks.append(
                {
                    "text": chunk.text,
                    "source_file": str(note_file),
                    "token_count": chunk.token_count,
                    "start_index": chunk.start_index,
                    "end_index": chunk.end_index,
                    "chunk_id": f"{note_file.stem}_{idx}",
                }
            )

    return all_chunks
