"""Phase 2 ingest pipeline.

Lives at `rag.ingest_v2` (not `rag.ingest`) to avoid shadowing the existing
v1 script `rag/ingest.py`, which keeps running until Phase 9 cutover.

Modules to land in Phase 2:
    - multimodal.py        Docling adapter for PDFs, DOCX, images
    - semantic_chunker.py  chonkie SemanticChunker wrapper (heading-aware)
    - late_chunker.py      jina-embeddings-v2-base-en mean-pool late chunking
    - metadata.py          frontmatter + wikilinks + lang detect
    - pipeline.py          orchestrator entry point
    - qdrant_writer.py     upsert into nexus-vault-v2
    - bm25_writer.py       rebuild rank_bm25 corpus snapshot
"""
