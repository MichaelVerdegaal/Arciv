# Personal Knowledge Graph

Clotho is your personal knowledge graph framework that helps you organize, retrieve, and leverage insights from your Obsidian markdown notes using natural language queries.

In ancient greek mythology, Clotho is one of the three Fates responsible for spinning the thread of life. And what is a knowledge graph, if not a web of interconnected threads of knowledge?

## What It Does

Transforms Obsidian markdown notes into a queryable knowledge graph that surfaces relevant past work, obstacles, solutions, and resources through natural language queries.

**Query examples:**
- "What problems did I face with my models in Q3?"
- "Show me resources about Polars performance"
- "Similar obstacles to my CUDA GPU utilization issue"

## Core Architecture

- **Storage**: HelixDB (unified graph + vector database)
- **Graph Construction**: LinearRAG approach (co-occurrence edges + semantic similarity, no expensive relation extraction)
- **Entity Resolution**: Embedding-based semantic blocking to prevent duplicates
- **Query**: Agentic system with hybrid retrieval (vector search + graph traversal + BM25)

## Key Design Decisions

1. **Lightweight entity extraction** - spaCy NLP, not LLM calls
2. **Three embedding types per note** - full content, technical context, resource context
3. **Incremental updates** - process only new/modified notes
4. **Schema evolution** - start minimal, expand based on patterns

## Tech Stack

- Python 3.12 with UV package manager
- HelixDB for graph-vector storage
- spaCy for entity extraction
- OpenRouter + Pydantic AI for agent LLM

## Useful references
- [HelixDB professor example](https://www.helix-db.com/blog/building-a-graphrag-system-for-professor-recommendations-with-helixdb)
- [HelixDB Python SDK documentation](https://docs.helix-db.com/documentation/sdks/helix-py)
- [LinearRAG paper](https://arxiv.org/html/2510.10114v4)
- [Semantic entity resolution](https://blog.graphlet.ai/the-rise-of-semantic-entity-resolution-45c48d5eb00a)
- [Personal knowledge graphs](https://personalknowledgegraphs.com/#/page/pkg)