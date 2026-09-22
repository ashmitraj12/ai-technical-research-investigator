# 🔬 AI Technical Research Investigator

An evidence-driven, agentic AI Technical Research Investigator powered by **Model Context Protocol (MCP)**, local LLM inference via **Ollama**, dynamic **ReAct reasoning**, **single-pass reflection**, structured **evidence synthesis**, and a real-time **Streamlit observability dashboard**.

---

## 1. Problem Statement

Developers and engineering teams waste substantial hours diagnosing technical problems because relevant information is fragmented across:
- Official framework documentation and migration guides
- GitHub repositories, pull requests, and closed issue trackers
- Release notes and changelogs
- Public technical advisories, RFCs, and blog posts
- Local repository manifests, configuration files, and source code

Standard chatbots often hallucinate library versions, invent nonexistent API methods, or guess root causes without checking actual code or primary sources.

---

## 2. Why This Problem Matters

1. **Hallucination Risk**: Guessing solutions for complex dependency breakages or breaking changes can lead to wasted engineering cycles or production regressions.
2. **Investigation Latency**: Manually searching multiple disjoint sources (GitHub, docs, local repo) takes significant developer time.
3. **Evidence Verification**: Real engineering decisions require traceable evidence—distinguishing **FACT** from **INFERENCE** and identifying when sources disagree.

---

## 3. The Solution

The **AI Technical Research Investigator** does not behave as a generic chatbot. Instead, it operates as an **autonomous investigator**:
- Formulates an investigation plan based on the user's inquiry.
- Dynamically selects and invokes genuine **MCP (Model Context Protocol)** tools via stdio transports.
- Ingests tool outputs into a deduplicated, structured **Evidence Store** (ranking source reliability).
- Performs a **single-pass reflection** to verify findings, cross-check contradictions, and assess confidence.
- Synthesizes a structured report with verified root causes, recommendations, and source citations.
- Emits real-time execution logs and measured telemetry (latencies, token counts, tool usage).

---

## 4. System Architecture

```
User Query / Local Path
         │
         ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                Streamlit UI Dashboard                       │
 │  (Sidebar Config, Live Log Terminal, Evaluation Matrix)     │
 └─────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                Agent Controller & ReAct Loop                │
 │       (Perceive -> Plan -> Act -> Observe -> Decide)        │
 └──────────────┬──────────────────────────────┬───────────────┘
                │                              │
                ▼                              ▼
 ┌───────────────────────────┐   ┌─────────────────────────────┐
 │   Ollama Local LLM API    │   │     MCP Client Manager      │
 │ (llama3.2 / JSON Parser)  │   │     (Stdio JSON-RPC 2.0)    │
 └───────────────────────────┘   └─────────────┬───────────────┘
                                               │
               ┌───────────────────────────────┼───────────────────────────────┐
               │                               │                               │
               ▼                               ▼                               ▼
 ┌───────────────────────────┐   ┌───────────────────────────┐   ┌───────────────────────────┐
 │   Web Search MCP Server   │   │  GitHub Research MCP      │   │  Local Repo MCP Server    │
 │ (DuckDuckGo / Web Fetch)  │   │  (Issues / Discussions)   │   │  (Files / Dependencies)   │
 └─────────────┬─────────────┘   └─────────────┬─────────────┘   └─────────────┬─────────────┘
               │                               │                               │
               └───────────────────────────────┼───────────────────────────────┘
                                               │
                                               ▼
                                ┌─────────────────────────────┐
                                │   Evidence Store & Parser   │
                                │ (Deduplication, Reliability)│
                                └──────────────┬──────────────┘
                                               │
                                               ▼
                                ┌─────────────────────────────┐
                                │      Reflection Engine      │
                                │ (Single-Pass Verification)  │
                                └──────────────┬──────────────┘
                                               │
                                               ▼
                                ┌─────────────────────────────┐
                                │  Evaluation & Telemetry     │
                                │ (Real Timers, Matrix Score) │
                                └─────────────────────────────┘
```

---

## 5. Model Context Protocol (MCP) Integration

This project uses a genuine **Model Context Protocol (MCP)** architecture:
- Process isolation via stdio JSON-RPC 2.0 communication.
- Dynamic tool discovery via protocol methods (`initialize`, `tools/list`, `tools/call`).
- High-resolution execution latency tracking per tool.
- Zero fake Python function imports masquerading as MCP tools.

---

## 6. The ReAct Agent Loop

The agent follows an autonomous ReAct cycle:
```
PERCEIVE ──> UNDERSTAND ──> DECIDE ──> ACT (MCP) ──> OBSERVE ──> DECIDE AGAIN ──> REFLECT ──> FINAL REPORT
```
- **Dynamic Tool Selection**: For general conceptual questions (e.g. *"What is Python?"*), the agent recognizes no external research is needed and skips tool execution.
- **Safety Limit**: Configurable maximum iterations (default: 5) and maximum MCP calls (default: 4) prevent runaway loops.

---

## 7. MCP Tools Reference

| Tool Name | MCP Server | Purpose |
|---|---|---|
| `inspect_local_repository` | `repo_server.py` | Inspects local files, directory trees, codebase search, and `requirements.txt`/`pyproject.toml` manifests. |
| `search_github_issues` | `github_server.py` | Searches GitHub issues, PRs, and community discussions with automatic web fallback. |
| `search_web` | `web_search_server.py` | DuckDuckGo web search for official documentation and technical release notes. |
| `fetch_web_document` | `web_search_server.py` | Downloads and parses clean text from specific web URLs for grounded verification. |

---

## 8. Technology Stack

- **Python**: 3.10+ (Standard library, `asyncio`, `subprocess`, `pydantic v2`)
- **Local LLM**: [Ollama](https://ollama.com/) (`llama3.2:1b`, `llama3.2:latest`, `qwen2.5`, `mistral`)
- **Tool Protocol**: Model Context Protocol (MCP JSON-RPC 2.0 Stdio)
- **Web UI**: Streamlit with custom CSS and real-time streaming components
- **Search & Retrieval**: DuckDuckGo Search, BeautifulSoup4, GitHub REST API
- **Testing**: Pytest, Pytest-asyncio

---

## 9. Installation & Setup

### 1. Prerequisites
- Python 3.10 or higher
- [Ollama](https://ollama.com/) installed and running locally

### 2. Download a Local LLM
```bash
ollama pull llama3.2:1b
# or
ollama pull llama3.2
```

### 3. Clone and Install Dependencies
```bash
git clone https://github.com/your-org/ai-technical-research-investigator.git
cd ai-technical-research-investigator
pip install -r requirements.txt
```

---

## 10. Running the Application

Launch the Streamlit web application:
```bash
streamlit run app/streamlit_app.py
```

Access the UI at: `http://localhost:8501`

---

## 11. Demonstration Scenarios

The application includes 5 pre-configured demonstration presets in the sidebar:

1. **Scenario 1: Direct Answer (No MCP Tool Needed)**
   - *Query*: "What is Python GIL (Global Interpreter Lock) and how does free-threading mode in Python 3.13 change it?"
   - *Behavior*: Agent answers directly without making redundant tool calls.
2. **Scenario 2: Technical Compatibility Research**
   - *Query*: "Why does FastAPI raise PydanticUserError for @validator after migrating from Pydantic v1 to Pydantic v2?"
   - *Behavior*: Agent calls `search_web` and `search_github_issues`, identifies `@field_validator` migration, and synthesizes root cause.
3. **Scenario 3: Local Repository Investigation**
   - *Query*: "Why is this FastAPI service failing on startup with Pydantic validator errors?"
   - *Target Repo*: `data/sample_project`
   - *Behavior*: Agent invokes `inspect_local_repository` to inspect `requirements.txt` and `app/models.py`, combining local findings with external docs.
4. **Scenario 4: Conflicting Community Evidence**
   - *Query*: "Is Python 3.14 officially released and recommended for production use as of today?"
   - *Behavior*: Agent detects pre-release vs stable differences across sources and notes contradiction in reflection.
5. **Scenario 5: Insufficient Evidence Handling**
   - *Query*: "Why did proprietary internal module 'lib-quantum-core-x99' crash inside cluster node cluster-omega-42?"
   - *Behavior*: Agent reports "INSUFFICIENT EVIDENCE" without hallucinating answers.

---

## 12. Observability & Evaluation Metrics

Every investigation captures real measured runtime telemetry:

- **Total Investigation Time**: Measured wall-clock duration
- **LLM Latency & Inferences**: Request-response time per Ollama call
- **MCP Tool Latencies**: Per-tool stdio execution timers
- **Token Counts**: Prompt and evaluation token counts
- **Evaluation Matrix Table**: Summary of measured telemetry
- **Qualitative Assessment Scores**: Quantitative-backed scores (Evidence Completeness, Source Quality, Answer Relevance, Reasoning Sufficiency, Tool Efficiency)

---

## 13. Project Structure

```
ai-technical-research-investigator/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── docs/
│   ├── DEVELOPMENT_LOG.md
│   ├── ARCHITECTURE.md
│   ├── MCP_TOOLS.md
│   ├── EVALUATION.md
│   └── DECISIONS.md
├── app/
│   ├── streamlit_app.py
│   ├── agent/
│   │   ├── agent.py
│   │   ├── planner.py
│   │   ├── state.py
│   │   ├── reflection.py
│   │   └── prompts.py
│   ├── mcp/
│   │   ├── protocol.py
│   │   ├── client.py
│   │   └── servers/
│   │       ├── repo_server.py
│   │       ├── github_server.py
│   │       └── web_search_server.py
│   ├── llm/
│   │   ├── ollama_client.py
│   │   └── models.py
│   ├── evaluation/
│   │   ├── metrics.py
│   │   ├── tracker.py
│   │   └── evaluator.py
│   ├── logging/
│   │   └── logger.py
│   └── evidence/
│       ├── models.py
│       └── manager.py
├── tests/
│   ├── test_agent.py
│   ├── test_mcp.py
│   ├── test_evaluation.py
│   ├── test_evidence.py
│   ├── test_ollama.py
│   ├── test_reflection.py
│   └── test_scenarios.py
└── data/
    └── sample_project/
        ├── requirements.txt
        ├── error_log.txt
        ├── README.md
        └── app/
            ├── main.py
            └── models.py
```

---

## 14. Testing

Run the full pytest suite:
```bash
pytest tests/ -v
```

---

## 15. Limitations & Future Work

- **Local Model Capacity**: Smaller local models (e.g. 1B-3B parameters) may occasionally produce formatting variations; robust regex/JSON fallback parsers are included.
- **Future Work**:
  - Add support for AST-based Python code graph analysis inside the Repo MCP server.
  - Multi-threaded asynchronous MCP tool dispatch.
  - Export investigation reports as PDF/Markdown files directly from the UI.

### Evidence and runtime limitations

- A repository path must exist and be accessible. Invalid input is rejected before any investigation starts.
- Search results are not evidence by themselves; the system must fetch and validate source content before treating it as verified evidence.
- Network, GitHub, DuckDuckGo, and Ollama outages are reported in the technical trace and metrics. The application returns a conservative insufficient-evidence report rather than inventing a root cause.
- Stable general-knowledge questions are classified by the configured local model and answered directly with zero MCP calls; an investigation is only started when the model classifies evidence as necessary.

---

## 16. License
MIT License.
