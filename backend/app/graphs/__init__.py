"""LangGraph-based orchestration for advanced RAG paths.

This package is **opt-in**. The default RAG path is still
:class:`app.rag.engine.RAGEngine`. The graph here is activated only
when ``RAG_USE_LANGGRAPH=true`` (see
:mod:`app.integrations.lc.settings`) and used by
:meth:`app.services.legal_service.LegalService._rag_answer` as an
alternative engine. Routing, memory, deterministic statute lookups,
and SSE streaming are unaffected.
"""
