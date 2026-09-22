"""
Streamlit Web Application for AI Technical Research Investigator.
Evidence-driven technical investigations using Model Context Protocol (MCP) and Local LLM (Ollama).
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

# Load .env file before anything else so GROQ_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed; fall back to plain env vars

import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import ResearchInvestigatorAgent
from app.llm.ollama_client import OllamaClient
from app.llm.groq_client import GroqClient, GROQ_MODELS
from app.mcp.client import MCPClientManager
from app.logging.logger import LogEvent, LogLevel, LogCategory
from app.evidence.models import SourceType, ReliabilityLevel, EvidenceCategory

# Streamlit Page Config
st.set_page_config(
    page_title="AI Technical Research Investigator",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for rich aesthetics and clean terminal logs
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin-bottom: 0.2rem;
        background: linear-gradient(135deg, #1d4ed8, #7e22ce);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .sub-header {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.2rem;
    }
    
    .badge {
        display: inline-block;
        padding: 0.25rem 0.65rem;
        font-size: 0.8rem;
        font-weight: 600;
        border-radius: 9999px;
        margin-right: 0.4rem;
    }
    .badge-high { background-color: #dcfce7; color: #15803d; border: 1px solid #86efac; }
    .badge-medium { background-color: #fef9c3; color: #a16207; border: 1px solid #fde047; }
    .badge-low { background-color: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
    .badge-info { background-color: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; }
    
    .status-timeline {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
        font-size: 0.95rem;
    }
    
    .terminal-box {
        background-color: #0f172a;
        color: #f8fafc;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #334155;
        height: 240px;
        overflow-y: auto;
        white-space: pre-wrap;
        line-height: 1.5;
        margin-bottom: 1rem;
    }
    
    .log-time { color: #64748b; }
    .log-agent { color: #38bdf8; font-weight: 600; }
    .log-mcp { color: #34d399; font-weight: 600; }
    .log-llm { color: #fbbf24; font-weight: 600; }
    .log-ref { color: #c084fc; font-weight: 600; }
    .log-sys { color: #94a3b8; font-weight: 600; }
    .log-err { color: #f87171; font-weight: 700; }
    
    .metric-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 0.5rem;
        padding: 0.9rem;
        text-align: center;
    }
    .metric-val { font-size: 1.4rem; font-weight: 700; color: #1e293b; }
    .metric-lbl { font-size: 0.8rem; color: #64748b; font-weight: 500; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_ollama_client():
    return OllamaClient()


@st.cache_resource
def get_mcp_client():
    client = MCPClientManager()
    client.discover_tools()
    return client


# Initialization
ollama_client = get_ollama_client()
mcp_client = get_mcp_client()

# ── Provider Initialisation (reads from .env / environment) ──────────────────
_groq_api_key   = os.environ.get("GROQ_API_KEY", "").strip()
_llm_provider   = os.environ.get("LLM_PROVIDER", "groq" if _groq_api_key else "ollama").strip().lower()
_default_model  = os.environ.get("DEFAULT_MODEL", "openai/gpt-oss-120b" if _llm_provider == "groq" else "qwen3.5:2b-q4_K_M").strip()

# Always check Ollama (used as fallback)
ollama_client = OllamaClient()
health_info = ollama_client.check_health()
is_ollama_online = health_info.get("status") == "healthy"
available_ollama_models = health_info.get("models", ["llama3.2:1b", "qwen3.5:2b-q4_K_M"])

# Check Groq if key is configured
use_groq = (_llm_provider == "groq") and bool(_groq_api_key)
if use_groq:
    _groq_client_check = GroqClient(api_key=_groq_api_key, default_model=_default_model)
    groq_health = _groq_client_check.check_health()
    is_groq_online = groq_health.get("status") == "healthy"
    available_groq_models = groq_health.get("models", GROQ_MODELS)
    preferred = [m for m in GROQ_MODELS if m in available_groq_models]
    other_groq = [m for m in available_groq_models if m not in GROQ_MODELS]
    available_groq_models = preferred + other_groq
else:
    is_groq_online = False
    available_groq_models = GROQ_MODELS
    groq_health = {}

# Shared MCP client
mcp_client = MCPClientManager()
mcp_client.discover_tools()

# Preset Scenarios
demo_scenarios = {
    "-- Custom Question --": {
        "query": "",
        "repo": ""
    },
    "Scenario 1: Direct Technical Question (No MCP Tools Needed)": {
        "query": "What is Python Global Interpreter Lock (GIL) and how does free-threading mode in Python 3.13 change it?",
        "repo": ""
    },
    "Scenario 2: Technical Compatibility Research (Web & GitHub MCP)": {
        "query": "Why does FastAPI raise PydanticUserError for @validator after migrating from Pydantic v1 to Pydantic v2?",
        "repo": ""
    },
    "Scenario 3: Local Repo Investigation (Repo & Manifest MCP)": {
        "query": "Why is my FastAPI application failing after upgrading Pydantic from version 1 to version 2?",
        "repo": str(PROJECT_ROOT / "data" / "sample_project")
    },
    "Scenario 4: Conflicting Community Evidence": {
        "query": "Is Python 3.14 officially released and recommended for production use as of today?",
        "repo": ""
    },
    "Scenario 5: Insufficient Evidence Handling": {
        "query": "Why did proprietary internal module 'lib-quantum-core-x99' crash inside cluster node cluster-omega-42?",
        "repo": ""
    }
}

# Sidebar configuration
with st.sidebar:
    st.markdown("### 🔬 Investigation System")
    
    chosen_scenario = st.selectbox("📂 Load Preset Scenario", options=list(demo_scenarios.keys()))
    
    st.divider()
    
    st.markdown("### 🔌 Runtime Connectivity")

    # ── Provider Status (read-only — configured in .env) ─────────────────────
    if use_groq:
        if is_groq_online:
            st.success(f"🟢 **Groq Connected** — `{_default_model}`  (`{groq_health.get('latency_sec', 0.0)}s`)")
        else:
            st.error(f"🔴 **Groq Error**: {groq_health.get('error', 'Unknown')}")
            st.caption("Check `GROQ_API_KEY` in your `.env` file.")
    else:
        if is_ollama_online:
            st.success(f"🟢 **Ollama Connected** (`{health_info.get('latency_sec', 0.0)}s`)")
        else:
            st.error(f"🔴 **Ollama Offline** — {health_info.get('error', 'Unreachable')}")
        if not _groq_api_key:
            st.info("💡 Add `GROQ_API_KEY` to `.env` to switch to free cloud models (faster & smarter).")

    st.info(f"🛠️ **MCP Tools**: **{len(mcp_client.tools)}** discovered")
    for tname, tinfo in mcp_client.tools.items():
        st.caption(f"• `{tname}` ({tinfo.server_id})")

    st.divider()

    with st.expander("⚙️ Advanced / Developer Settings", expanded=False):
        if use_groq:
            selected_model = st.selectbox(
                "Groq Model",
                options=available_groq_models,
                index=0,
                help="llama-3.3-70b-versatile is the most capable free model."
            )
        else:
            selected_model = st.selectbox(
                "Ollama Model",
                options=available_ollama_models,
                index=0,
                help="Select local LLM model running in Ollama."
            )
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            max_iterations = st.slider("Max Iterations", min_value=1, max_value=20, value=12, step=1)
        with col_s2:
            max_mcp_calls = st.slider("Max MCP Calls", min_value=1, max_value=20, value=10, step=1)
        temperature = st.slider("LLM Temperature", min_value=0.0, max_value=1.0, value=0.1, step=0.05)


# Main Page Header
st.markdown('<div class="main-header">AI Technical Research Investigator</div>', unsafe_allow_html=True)
_provider_label = "Groq Cloud LLM" if st.session_state.get("llm_provider") == "groq" else "Local LLM (Ollama)"
st.markdown(f'<div class="sub-header">Evidence-driven technical investigation using Model Context Protocol (MCP) & {_provider_label}</div>', unsafe_allow_html=True)

# User Query Inputs
default_query = demo_scenarios[chosen_scenario]["query"]
default_repo = demo_scenarios[chosen_scenario]["repo"]

query_input = st.text_area(
    "Research Question / Technical Problem",
    value=default_query,
    height=90,
    placeholder="e.g. Why is my FastAPI application failing after upgrading Pydantic from version 1 to version 2?"
)

col_repo, col_btn = st.columns([3, 1])
with col_repo:
    repo_input = st.text_input(
        "Local Repository / Workspace Directory (Optional)",
        value=default_repo,
        placeholder="e.g. C:/projects/my_app or leave empty for external research only"
    )
    # Path validation status
    if repo_input.strip():
        resolved_p = Path(repo_input.strip()).resolve()
        if resolved_p.exists() and resolved_p.is_dir():
            st.caption(f"✅ Target directory verified: `{resolved_p}`")
        else:
            st.error("Repository path does not exist. Please select a valid repository.")
    else:
        st.caption("🌐 No local repository provided — external research mode.")

with col_btn:
    st.write("")
    st.write("")
    investigate_clicked = st.button("🚀 Investigate", type="primary", use_container_width=True)

# State placeholders
if "investigation_results" not in st.session_state:
    st.session_state.investigation_results = None
if "live_logs" not in st.session_state:
    st.session_state.live_logs = []


# Execution Handler
if investigate_clicked:
    if not query_input.strip():
        st.error("Please enter a technical research question to investigate.")
    else:
        # Validate repository path before launching
        resolved_repo = None
        if repo_input.strip():
            candidate = Path(repo_input.strip()).resolve()
            if candidate.exists() and candidate.is_dir():
                resolved_repo = str(candidate)
            else:
                st.error("Repository path does not exist. Please select a valid repository.")
                st.stop()

        st.session_state.live_logs = []
        
        # Real-time UI progress containers
        timeline_box = st.empty()
        log_box = st.empty()
        
        timeline_events = [
            "⚡ Request received and analysis started..."
        ]

        def on_log_event(event: LogEvent):
            st.session_state.live_logs.append(event)
            # High level activity timeline update
            if event.category == "AGENT" and "Iteration" in event.message:
                timeline_events.append(f"🔄 {event.message}")
            elif event.category == "MCP" and "Calling" in event.message:
                timeline_events.append(f"🛠️ {event.message}")
            elif event.category == "REFLECTION":
                timeline_events.append(f"🛡️ {event.message}")
            
            # Update live timeline display
            timeline_html = "<br>".join([f"• {msg}" for msg in timeline_events[-4:]])
            timeline_box.markdown(f'<div class="status-timeline"><strong>Investigation Progress</strong><br>{timeline_html}</div>', unsafe_allow_html=True)

        # Build the active LLM client from .env configuration
        if use_groq and _groq_api_key:
            active_llm_client = GroqClient(
                api_key=_groq_api_key,
                default_model=selected_model if 'selected_model' in locals() else _default_model
            )
        else:
            if use_groq and not _groq_api_key:
                st.error("⚠️ `LLM_PROVIDER=groq` set but `GROQ_API_KEY` is empty in `.env`. Please add your key.")
                st.stop()
            active_llm_client = ollama_client

        agent = ResearchInvestigatorAgent(ollama_client=active_llm_client, mcp_client=mcp_client)
        
        with st.spinner("Investigating root cause and verifying evidence across MCP tools..."):
            results = agent.investigate(
                query=query_input.strip(),
                repo_path=resolved_repo,
                model_name=selected_model if 'selected_model' in locals() else "llama3.2:1b",
                max_iterations=max_iterations if 'max_iterations' in locals() else 6,
                max_mcp_calls=max_mcp_calls if 'max_mcp_calls' in locals() else 5,
                temperature=temperature if 'temperature' in locals() else 0.1,
                log_callback=on_log_event
            )
            st.session_state.investigation_results = results
            
        timeline_box.empty()


# Results Presentation
if st.session_state.investigation_results:
    res = st.session_state.investigation_results
    metrics = res["metrics"]
    evidence_mgr = res["evidence_manager"]
    evidence_items = evidence_mgr.get_all_evidence()
    reflection_data = res.get("reflection", {})
    matrix_rows = res.get("evaluation_matrix", [])
    qualitative = res.get("qualitative_scores")
    logs = res.get("logs", [])

    st.markdown("---")
    st.markdown("### 📊 Investigation Results & Telemetry")

    # Metric Banner
    col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)
    with col_m1:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{metrics.total_investigation_time_sec:.2f}s</div><div class="metric-lbl">Total Time</div></div>', unsafe_allow_html=True)
    with col_m2:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{metrics.total_llm_calls}</div><div class="metric-lbl">LLM Inferences</div></div>', unsafe_allow_html=True)
    with col_m3:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{metrics.total_mcp_calls}</div><div class="metric-lbl">MCP Tool Calls</div></div>', unsafe_allow_html=True)
    with col_m4:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{len(evidence_items)}</div><div class="metric-lbl">Evidence Items</div></div>', unsafe_allow_html=True)
    with col_m5:
        conf_color = "badge-high" if metrics.final_confidence_percent >= 80 else ("badge-medium" if metrics.final_confidence_percent >= 60 else "badge-low")
        st.markdown(f'<div class="metric-card"><div class="metric-val"><span class="badge {conf_color}">{metrics.final_confidence_percent}%</span></div><div class="metric-lbl">Confidence</div></div>', unsafe_allow_html=True)
    with col_m6:
        err_badge = "badge-high" if metrics.error_count == 0 else "badge-low"
        st.markdown(f'<div class="metric-card"><div class="metric-val"><span class="badge {err_badge}">{metrics.error_count}</span></div><div class="metric-lbl">Errors</div></div>', unsafe_allow_html=True)

    st.write("")

    # Result Tabs
    tab_report, tab_evidence, tab_sources, tab_eval, tab_activity, tab_logs = st.tabs([
        "📋 Investigation Report",
        "🔍 Grounded Evidence",
        "🌐 Verified Sources",
        "📈 Observability Matrix",
        "🛠️ Agent Activity & Traces",
        "📜 Technical Execution Logs"
    ])

    # TAB 1: Report
    with tab_report:
        st.markdown(res["final_report"])
        
        with st.expander("🛡️ Single-Pass Reflection Verification Summary", expanded=True):
            st.markdown(f"**Verification Status**: `{reflection_data.get('reflection_summary', 'Completed')}`")
            st.markdown(f"**Evidence Sufficiency**: {'✅ Sufficient' if reflection_data.get('is_evidence_sufficient') else '⚠️ Insufficient / Incomplete'}")
            st.markdown(f"**Fact vs. Inference**: {reflection_data.get('fact_vs_inference_check', 'Verified against evidence.')}")
            
            contradictions = reflection_data.get("contradictions_found", [])
            if contradictions:
                st.warning(f"**Contradictions / Gaps**: {', '.join(contradictions)}")
            else:
                st.success("✅ **Contradictions Check**: No conflicting source claims detected.")

    # TAB 2: Evidence
    with tab_evidence:
        st.markdown(f"#### 🧬 Gathered Evidence Items ({len(evidence_items)})")
        if not evidence_items:
            if metrics.evidence_required:
                st.warning("⚠️ External research evidence was required for this investigation, but was unavailable because MCP tool calls failed or returned no results.")
            else:
                st.info("No external evidence was required for this investigation (direct general technical inquiry).")
        else:
            for item in evidence_items:
                with st.container():
                    rel_class = "badge-high" if item.reliability == ReliabilityLevel.HIGH else ("badge-medium" if item.reliability == ReliabilityLevel.MEDIUM else "badge-low")
                    vstatus_badge = "badge-high" if item.verification_status == "VERIFIED" else "badge-info"
                    st.markdown(f"##### `{item.id}` — {item.title}")
                    st.markdown(f'<span class="badge {vstatus_badge}">{item.verification_status}</span> <span class="badge badge-info">{item.category.value}</span> <span class="badge {rel_class}">Reliability: {item.reliability.value}</span>', unsafe_allow_html=True)
                    st.markdown(f"**Source Path / URL**: `{item.url_or_path}`")
                    st.markdown(f"**Relationship to Conclusion**: *{item.relationship_to_conclusion}*")
                    if item.supports_claim:
                        st.markdown(f"**Supports Claim**: `{item.supports_claim}`")
                    st.markdown(f"```text\n{item.finding}\n```")
                    st.divider()

    # TAB 3: Sources
    with tab_sources:
        st.markdown("#### 📚 Verified Source References")
        if not evidence_items:
            if metrics.evidence_required:
                st.caption("External sources were required but unavailable due to tool execution failures.")
            else:
                st.caption("Standard Python Technical Knowledge Base (Direct inference).")
        else:
            unique_sources = {}
            for item in evidence_items:
                if item.url_or_path not in unique_sources:
                    unique_sources[item.url_or_path] = item
            
            for path_url, item in unique_sources.items():
                if path_url.startswith("http"):
                    st.markdown(f"- 🔗 [{item.title}]({path_url}) — *{item.source}* ({item.verification_status})")
                else:
                    st.markdown(f"- 📁 `{path_url}` — *{item.source}* ({item.verification_status})")

    # TAB 4: Evaluation Matrix
    with tab_eval:
        st.markdown("#### 📐 Runtime Evaluation Matrix (Measured Telemetry)")
        st.table([{"Metric": r.metric, "Measured Value": r.value, "Observation / Notes": r.notes} for r in matrix_rows])

        st.markdown("#### 🎯 Quantitative-Backed Qualitative Scores")
        if qualitative:
            col_q1, col_q2, col_q3 = st.columns(3)
            with col_q1:
                st.metric("Evidence Completeness", f"{qualitative.evidence_completeness} / 10")
                st.metric("Source Quality", f"{qualitative.source_quality} / 10")
            with col_q2:
                st.metric("Answer Relevance", f"{qualitative.answer_relevance} / 10")
                st.metric("Reasoning Sufficiency", f"{qualitative.reasoning_sufficiency} / 10")
            with col_q3:
                st.metric("Tool Selection Efficiency", f"{qualitative.tool_selection_efficiency} / 10")
                st.markdown(f"**Contradiction Check**: `{qualitative.contradiction_detection}`")

    # TAB 5: Activity & Traces
    with tab_activity:
        st.markdown("#### 🔄 ReAct Step-by-Step Decision History")
        agent_state = res["agent_state"]
        if not agent_state.history:
            st.caption("Direct synthesis (No tool steps).")
        else:
            for step in agent_state.history:
                st.markdown(f"**Iteration {step['iteration']} | Role: `{step['role']}`** ({step.get('tool_name', 'Agent')})")
                st.code(step['content'], language="text")

    # TAB 6: Live Logs
    with tab_logs:
        st.markdown("#### 📝 Authoritative Execution Log Stream")
        formatted_logs = [f"[{e.timestamp}] [{e.level}] [{e.category}] {e.message}" for e in logs]
        st.code("\n".join(formatted_logs), language="text")
