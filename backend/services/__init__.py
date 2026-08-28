"""Capabilities — self-contained async services with a degradation story.

llm, embeddings, vectorstore, search, memory, tts, stt, model serving, mail,
dav. Each presents a clean async interface and could run in-process or behind
HTTP. Reused by tools (the agent calls them), by research (calls directly), and
by plain routes (the user calls directly) — logic never hides in a tool.
Absence degrades the dependent feature gracefully.

Stub — no services yet. See docs/architecture/README.md (Pillar III, §2.3).
"""
