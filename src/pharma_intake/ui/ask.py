"""Ask tab: assistant routed by the deterministic control plane."""
from __future__ import annotations

import streamlit as st

from .. import config
from ..agent.orchestrator import AgentOrchestrator
from ..db import Database
from ..rag.generator import default_client
from ..rag.pipeline import HybridRetriever, load_report_documents, load_sop_documents
from .safe_text import escape_md

EXAMPLES = ("e.g. “LOT-88392 anaphylaxis”, “difficulty breathing”, “who approves closure?”, "
            "“move REF-2026-0001 to in review”, “submit report”")
MODE_LABEL = {"llm": "LLM answer (grounded)", "extractive": "Extractive answer", "no_source": "No source"}


def _orchestrator(db: Database) -> AgentOrchestrator:
    orch = st.session_state.get("agent")
    if orch is None or orch.db.path != db.path:
        orch = AgentOrchestrator(
            db, lambda: HybridRetriever(load_sop_documents() + load_report_documents(db))
        )
        st.session_state["agent"] = orch
    return orch


def render_ask() -> None:
    db = Database(config.DB_PATH)
    client = default_client()
    allow = st.sidebar.toggle(
        "Allow external LLM call (OpenRouter)",
        value=False,
        disabled=client is None,
        help="Off by default. Sends the question and retrieved excerpts to OpenRouter. "
        "Blocked if personal data is detected. "
        + ("" if client else "No OPENROUTER_API_KEY configured."),
    )
    orch = _orchestrator(db)
    orch.runtime.llm_client, orch.runtime.allow_external = client, allow

    if orch.breaker.tripped:
        st.error("Circuit breaker is OPEN: tool execution is halted after repeated invalid calls.")
        if st.button("Reset circuit breaker", key="btn_reset_breaker"):
            orch.reset_breaker()
            st.rerun()

    query = st.text_input("Ask about SOPs or past reports, or request an action", placeholder=EXAMPLES)
    if st.button("Send", key="btn_ask") and query.strip():
        resp = orch.handle(query)
        st.caption(f"Route: {resp.route.value}")
        st.markdown(escape_md(resp.text))
        data = resp.tool_result.data if resp.tool_result and resp.tool_result.ok else {}
        if "answer" in data:
            ans, retrieval = data["answer"], data["retrieval"]
            st.caption(f"Mode: {MODE_LABEL[ans.mode]}" + (f" — {escape_md(ans.reason)}" if ans.reason else ""))
            with st.expander("Retrieval trace"):
                st.write(
                    f"BM25 candidates: {len(retrieval.bm25_ids)} · Dense candidates: "
                    f"{len(retrieval.dense_ids)} · Fused pool: {len(retrieval.fused_ids)} · "
                    f"Selected (score ≥ {config.RERANK_THRESHOLD}): {len(retrieval.selected)}"
                )
                st.dataframe(
                    [{"Chunk": s.chunk.chunk_id, "Source": s.chunk.source, "Rerank score": round(s.score, 3)}
                     for s in retrieval.reranked[:10]],
                    hide_index=True,
                )

    with st.expander("Agent trace (Thought → Action → Observation)"):
        if not orch.short_term.steps:
            st.write("No steps yet.")
        for i, s in enumerate(orch.short_term.steps[-10:], 1):
            st.markdown(f"**{i}.** *Thought:* {escape_md(s.thought)}  \n*Action:* `{s.action}`  \n*Observation:* {escape_md(s.observation)}")
