export interface Citation {
  id: string;
  type: "case" | "statute" | "provision" | "article";
  title: string;
  citation: string;
  court: string;
  year?: string;
  excerpt?: string;
}

// ── Backend (/api/v1/query) response shapes ──────────────────────────────────

export interface BackendEntity {
  type: string;
  value: string;
  confidence: number;
  start: number;
  end: number;
}

export interface StatuteSection {
  number: string;
  title: string;
  content: string;
  citations: string[];
}


// ── Chat UI model ────────────────────────────────────────────────────────────

/** Compact per-chunk retrieval record — see backend RetrievedChunkRecord. */
export interface RetrievedChunkRecord {
  source: string;
  similarity: number;
  rerank_score: number | null;
  rerank_reason: string | null;
  section: string;
  act: string;
  excerpt: string;
  // Hybrid-retrieval stage diagnostics (all optional — older ingestion
  // paths surface only similarity + rerank_score).
  vector_score?: number | null;
  vector_rank?: number | null;
  bm25_score?: number | null;
  bm25_rank?: number | null;
  fused_score?: number | null;
  fused_rank?: number | null;
  cross_encoder_score?: number | null;
}

export interface MessageAnalysis {
  intent: string;
  route: string;
  confidence: number;
  reason: string;
  entities: BackendEntity[];
  domain?: string | null;
  relatedActs?: string[];
  suggestions?: string[];
  /** Top reranked chunks emitted by the RAG path (empty on deterministic). */
  retrievedChunks?: RetrievedChunkRecord[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  citations?: Citation[];
  tags?: string[];
  analysis?: MessageAnalysis;
  isError?: boolean;
  streaming?: boolean;
}

// ── SSE streaming ────────────────────────────────────────────────────────────

export interface StreamMeta {
  query: string;
  intent: string;
  route: string;
  confidence: number;
  reason: string;
  entities: BackendEntity[];
  statute_sections: StatuteSection[];
  domain?: string | null;
  related_acts?: string[];
  suggestions?: string[];
  /** Snake-case to match the wire shape coming from the SSE meta event. */
  retrieved_chunks?: RetrievedChunkRecord[];
}

export interface StreamCallbacks {
  onMeta: (meta: StreamMeta) => void;
  onToken: (text: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
}
