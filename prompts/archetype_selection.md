# Archetype Selection Prompt

You are selecting the best resume archetype for a job description.

Available archetypes:
- A_general_ai_platform
- B_fintech_transaction_systems
- C_data_streaming_systems
- D_distributed_systems

Rules:
1. Choose the archetype that best matches the dominant job language.
2. Prefer fintech when correctness, auditability, transactions, or compliance are emphasized.
3. Prefer data/streaming when ingestion, pipelines, analytics, or real-time systems dominate.
4. Prefer distributed systems when low latency, concurrency, and fault tolerance dominate.
5. Prefer general AI/platform when platform engineering or AI-adjacent tooling is the clearest fit.
6. Output JSON only:
{
  "archetype_id": "...",
  "score": 0.0,
  "reasons": ["...", "..."]
}
