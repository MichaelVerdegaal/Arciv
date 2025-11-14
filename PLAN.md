# Project Plan: Personal Knowledge Graph

## Vision

Build a queryable memory system from daily work notes that surfaces relevant context, patterns, and solutions through natural language queries.

## Core Approach

### Philosophy
**Simple over sophisticated** - Start with lightweight techniques (co-occurrence, semantic similarity) before adding complexity. Avoid premature optimization.

### Key Principles
1. **LinearRAG Construction** - Skip expensive LLM relation extraction. Use co-occurrence + semantic similarity edges.
2. **Semantic Entity Resolution** - Prevent duplicates at ingestion time via embedding similarity, not after-the-fact cleanup.
3. **Multi-Embedding Strategy** - Generate specialized embeddings (full, technical, resources) for targeted retrieval.
4. **Incremental Updates** - Process only new/modified notes. Daily additions take seconds, not minutes.

---

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
**Goal**: Parse notes → Extract entities → Store in HelixDB

**Tasks**:
- Set up HelixDB locally with initial schema (DailyNote, Project, TechnicalObstacle, Resource, Technology, Person)
- Build markdown parser handling Obsidian syntax (frontmatter, [[wiki-links]], #tags, sections)
- Implement basic entity extraction with spaCy (person, project, technology)
- Ingest first 50 notes and validate with simple queries

**Success Criteria**: 50 notes queryable with basic filtering ("show notes mentioning Project X", "list all technologies")

**Key Files**: `parsers/markdown.py`, `extractors/entities.py`, `schema/v1.hql`

---

### Phase 2: Entity Resolution & Embeddings (Weeks 3-4)
**Goal**: Prevent duplicates + Generate semantic search capability

**Tasks**:
- Implement semantic blocking (embed entity names → check similarity before creation)
- Build LLM-based disambiguation for ambiguous matches (similarity 0.7-0.85)
- Create canonical entity registry (JSON mapping: aliases → canonical IDs)
- Generate three embedding types per note (full, technical context, resources)
- Build vector indexes in HelixDB for each embedding type

**Success Criteria**: <5% entity duplication rate. All 311 notes embedded with searchable indexes.

**Key Files**: `resolution/semantic_blocking.py`, `resolution/llm_resolver.py`, `embeddings/generator.py`

---

### Phase 3: Graph Enrichment (Weeks 5-6)
**Goal**: Add semantic and temporal relationships for better retrieval

**Tasks**:
- Create co-occurrence edges (entities mentioned together in same note/section)
- Add semantic similarity edges between entities (threshold 0.75)
- Implement temporal relationships (NEXT_DAY, SAME_WEEK, SAME_SPRINT)
- Build cross-reference detection (notes sharing entities, tags, resources)
- Create HelixQL query template library for common patterns

**Success Criteria**: Graph has 1000+ edges. Query templates cover 80% of use cases with <500ms latency.

**Key Files**: `graph/semantic_linker.py`, `graph/temporal_linker.py`, `queries/templates.py`

---

### Phase 4: Query Agent (Weeks 7-8)
**Goal**: Natural language queries with hybrid retrieval

**Tasks**:
- Build agent with tool registry (semantic_search, graph_traversal, temporal_query, fulltext, aggregation)
- Implement hybrid retrieval (vector + BM25 + graph with RRF reranking)
- Create CLI for natural language questions
- Set up incremental update pipeline (process only new notes)
- Build simple Streamlit UI for graph visualization (optional)

**Success Criteria**: Agent answers test queries with 90%+ precision, 80%+ recall, <2s latency.

**Key Files**: `agent/core.py`, `agent/tools.py`, `retrieval/hybrid.py`, `cli.py`

---

## Technical Decisions

### Why LinearRAG?
Traditional GraphRAG costs $5-10 in LLM calls for 311 notes. LinearRAG uses co-occurrence + semantic similarity for free, achieving 90% of the quality.

**Trade-off**: Lose explicit typed relationships (CAUSES, SOLVED_BY) but gain speed and zero cost. For personal KBs, co-occurrence is sufficient.

### Why Three Embeddings?
Query "React performance problems" should match technical contexts (obstacles + technologies), not notes merely mentioning React in passing. Specialized embeddings = better retrieval precision.

### Why Semantic Blocking?
Cleaning up duplicates post-ingestion is painful. Blocking at ingestion time (check before create) prevents fragmentation from day one.

### Why HelixDB?
Native graph + vector integration. One database, one query language. Alternatives (Neo4j + Qdrant) require middleware and sync logic.

---

## Data Flow

```
Obsidian Note (.md)
    ↓
Markdown Parser → Structured sections + metadata
    ↓
Entity Extractor (spaCy) → Entities by type
    ↓
Entity Resolver → Canonical entities (blocks duplicates)
    ↓
Embedding Generator → 3 embeddings per note
    ↓
Graph Builder → Nodes + co-occurrence edges
    ↓
Semantic Linker → Similarity edges between entities
    ↓
HelixDB → Queryable graph
    ↓
Query Agent → Natural language answers
```

---

## Iteration Strategy

### Start Minimal
**Week 1-2**: Only DailyNote, Project, Person nodes. Basic parsing. No entity resolution yet.

**Week 3-4**: Add TechnicalObstacle, Resource, Technology. Implement resolution.

**Week 5-6**: Add Insight, Task nodes if patterns emerge in data.

### Validate Early
Test on 10 notes → 50 notes → 100 notes before full batch. Catch pipeline bugs when they affect 10 entities, not 500.

### Measure Quality
Track metrics at each phase:
- Entity extraction recall (manual sample of 20 notes)
- Duplicate rate (entities with similarity >0.9)
- Query relevance (precision/recall on test queries)
- Query latency (p50, p95, p99)

---

## Risks & Mitigations

**Risk**: Entity extraction misses domain-specific terms
**Mitigation**: Extend spaCy patterns with custom rules. Example: "TFT", "CUDA OOM", "Hydra config" won't be in default models.

**Risk**: Semantic blocking misses subtle duplicates ("React hooks" vs "React Hooks API")
**Mitigation**: LLM resolver catches these with 0.7-0.85 similarity. Human review loop for low confidence.

**Risk**: Graph becomes too dense (too many edges)
**Mitigation**: Prune low-weight similarity edges. Keep only top-k neighbors per entity.

**Risk**: Query agent costs accumulate
**Mitigation**: Cache LLM responses for tool selection. Most queries follow patterns.

---

## Success Metrics

**Phase 1**: 50 notes ingested with entities extracted
**Phase 2**: <5% duplicate rate across 311 notes
**Phase 3**: 1000+ edges connecting entities
**Phase 4**: Agent answers 10 test queries with 90%+ relevance

**Final Goal**: "Does this actually help me find relevant past work faster than grep/Obsidian search?"
→ Measure: Time to answer 10 real questions (before vs after system)

---

## Future Enhancements (Post-Week 8)

- Add "literature" folder processing (exported papers, blog posts)
- Implement graph summarization for "weekly review" queries
- Multi-hop reasoning for complex questions
- Graph visualization UI for exploring connections
- Export to Obsidian graph view format