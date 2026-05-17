"""Phase 4 ingest pipeline.

Lives at ``rag.ingest_v2`` (not ``rag.ingest``) so it does not shadow the
existing v1 script ``rag/ingest.py``, which keeps running until cutover.

Modules:
    types.py            ChunkBoundary, IngestChunk, IngestResult dataclasses
    multimodal.py       Docling adapter — PDF/DOCX/PPTX/HTML → Markdown
    semantic_chunker.py chonkie SemanticChunker → ChunkBoundary list
    late_chunker.py     jina-v2 mean-pool late chunking math
    metadata.py         frontmatter, wikilinks, tags, dates, stable ids
    qdrant_writer.py    collection init + idempotent upsert
    pipeline.py         end-to-end orchestrator (ingest_file / ingest_paths)
    cli.py              argparse CLI for ``python -m rag.ingest_v2``
"""
