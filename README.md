<div align="center">
  <h1>🌌 Nexus RAG</h1>
  <p><strong>Enterprise-Grade, Stateful Retrieval-Augmented Generation for Automated Customer Engagement</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/Docker-Enabled-2496ED.svg?logo=docker" alt="Docker" />
    <img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi" alt="FastAPI" />
    <img src="https://img.shields.io/badge/LangGraph-Stateful-FF4F00.svg" alt="LangGraph" />
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
  </p>
</div>

---

Nexus is a sovereign, high-fidelity RAG architecture designed to bridge the gap between internal knowledge bases (like an Obsidian PARA vault) and fully automated, public-facing client interactions. Engineered for strict reliability and latency reduction, Nexus is webhook-ready to handle high-volume traffic from platforms like Facebook Messenger via automation orchestration tools like n8n and Make.

## ✨ Core Features

- **Hybrid Retrieval Engine**: Combines dense vector search (Qdrant) and sparse lexical search (BM25) merged with Reciprocal Rank Fusion (RRF) for unparalleled exact-match accuracy.
- **Stateful Conversational Memory**: Utilizes `LangGraph` to maintain multi-turn session states, ensuring the agent remembers context throughout complex customer inquiries.
- **B.R.I.X. Optimized Prompting**: Built-in system architecture tailored to the BRIX framework—dynamically generating responses that **B**uild attention, **R**elate to the problem, **I**nspire action, and e**X**ecute conversion natively within the chat UI.
- **Zero-Hallucination Guardrails**: Implements strict programmatic boundary detection to halt uncertainty streams and gracefully hand over to human agents when confidence thresholds drop.
- **Advanced Ingestion Pipeline**: Features semantic boundary chunking, "Late Chunking" paradigms via Jina Embeddings, and cross-encoder reranking (`bge-reranker-v2-m3`).
- **Complete Observability**: Integrated with `Langfuse` and OpenTelemetry for deep granular tracing of LLM logic, latency, and costs.

## 🏗 Architecture

Code output
File generated successfully.

```mermaid
graph TD
    A[Facebook Messenger] -->|Webhook| B(n8n / Make)
    B -->|POST Payload| C[FastAPI Routing Layer]
    
    subgraph Nexus Backend Engine
        C --> D{LangGraph Agent Orchestrator}
        D <--> E[(Redis Semantic Cache)]
        D --> F[Retrieval Engine]
        
        subgraph Hybrid Search
            F --> G[(Qdrant Dense Vectors)]
            F --> H[(BM25 Lexical)]
            G --> I[Reciprocal Rank Fusion RRF]
            H --> I
            I --> J[Cross-Encoder Reranker]
        end
        
        J --> K[LLM Generation Provider via LiteLLM]
        K --> L[Guardrails Output Validation]
    end
    
    L -->|Verified Response| C
    C -->|Response| B
    B -->|API Delivery| A
    
    D -.-> Z[Langfuse Observability]
