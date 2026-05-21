"""External-framework integration boundary.

Submodules here adapt third-party orchestration tooling to LawFlow's
existing services. They MUST NOT replace authoritative components
(routing, memory, statute service, evaluation, rerank, vector store);
they only wrap them so that opt-in features (LangSmith tracing,
LangGraph RAG orchestration) can be layered on without touching the
core architecture.
"""
