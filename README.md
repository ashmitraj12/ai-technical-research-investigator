# 🔬 AI Technical Research Investigator

An evidence-driven, agentic AI Technical Research Investigator powered by genuine **Model Context Protocol (MCP)** stdio tools, a **Hybrid LLM Engine (Local Ollama & High-Throughput Cloud Groq)**, autonomous **ReAct reasoning**, **strategic query classification**, **two-stage evidence verification**, **single-pass reflection**, and a real-time **Streamlit observability dashboard**.

---

## 1. Problem Statement

Engineering teams spend countless hours diagnosing technical bugs, framework migrations, and version incompatibilities because relevant information is fragmented across disparate sources:
- Official framework documentation and migration guides
- GitHub repositories, pull requests, commit diffs, and issue trackers
- Package release notes, changelogs, and vulnerability advisories
- Local repository manifests (`requirements.txt`, `pyproject.toml`), configuration files, and source code

Standard LLM chatbots frequently hallucinate version numbers, invent nonexistent API methods, or guess root causes without inspecting real code or grounded primary sources.

---

## 2. Why This Problem Matters

1. **Hallucination Risk**: Guessing solutions for complex dependency breakages or breaking changes can lead to wasted engineering cycles or production regressions.
2. **Investigation Latency**: Manually searching multiple disjoint sources (GitHub, docs, local repo) takes significant developer time.
3. **Evidence Verification**: Real engineering decisions require traceable evidence—distinguishing **FACT** from **INFERENCE** and identifying when sources disagree.

---

## 3. The Solution

The **AI Technical Research Investigator** does not behave as a generic chatbot. Instead, it operates as an **autonomous investigator**:
- **Strategic Pre-Flight Classification**: Classifies whether a question is stable general knowledge (direct synthesis with 0 tool calls) or requires empirical external/local research.
- **Strict Boundary Validation**: Validates local repository existence upfront to eliminate phantom evidence.
- **Genuine MCP Stdio Subprocesses**: Dynamically discovers and calls process-isolated MCP tools via JSON-RPC 2.0 stdio transports.
- **Two-Stage Evidence Ingestion**: Ingests findings into a deduplicated store, distinguishing preliminary `RETRIEVED` search hits from fully fetched, validated `VERIFIED` evidence items.
- **Single-Pass Reflection Engine**: Verifies findings, checks fact vs. inference, detects cross-source contradictions, and calculates a confidence score (0%–100%).
- **Empirical Telemetry & Observability**: Measures real wall-clock latency, per-tool stdio execution timers, LLM inference latency, token counts, and quantitative-backed qualitative assessment scores (0–10 scale).

---

## 4. System Architecture

```text
+==================================================================================================+
|                        AI TECHNICAL RESEARCH INVESTIGATOR — ARCHITECTURE FLOW                    |
+==================================================================================================+

                                    +-----------------------------+
                                    |     [1] USER INPUT ENTRY    |
                                    | Technical Query & Repo Path |
                                    +-----------------------------+
                                                   |
                                                   v
                                    +-----------------------------+
                                    |     [2] STREAMLIT WEB UI    |
                                    |   (app/streamlit_app.py)    |
                                    +-----------------------------+
                                                   |
                                                   v
                                    +-----------------------------+
                                    | [3] PRE-FLIGHT VALIDATION   |
                                    | Target Repo Path on Disk?   |
                                    +-----------------------------+
                                          /                 \
                          [Path Invalid] /                   \ [Valid or No Path]
                                        v                     v
                         +--------------------+    +-----------------------------+
                         | HALT EXECUTION     |    | [4] SYSTEM INITIALIZATION   |
                         | Display UI Error   |    | Connect LLM & Discover Tools|
                         +--------------------+    +-----------------------------+
                                                                  |
                                                                  v
                                                   +-----------------------------+
                                                   | [5] STRATEGIC CLASSIFICATION|
                                                   | Intent & Evidence Required? |
                                                   +-----------------------------+
                                                         /                 \
                                   [evidence_required=False]             [evidence_required=True]
                                       (General Concept)                 (Bug / Version / Repo)
                                                       /                     \
                                                      v                       v
                         +-------------------------------+  +------------------------------------+
                         | DIRECT SYNTHESIS PATH         |  | [6] AUTONOMOUS ReAct AGENT LOOP    |
                         | Fast Single LLM Response      |  | Perception -> Planning -> Tool Act |
                         | (Zero MCP Tool Calls)         |  | (app/agent/agent.py & planner.py)  |
                         +-------------------------------+  +------------------------------------+
                                         |                                    |
                                         |                                    v
                                         |                  +------------------------------------+
                                         |                  | [7] MCP TOOL EXECUTION GATEWAY     |
                                         |                  | Stdio Subprocess (JSON-RPC 2.0)    |
                                         |                  +------------------------------------+
                                         |                                    |
                                         |         +--------------------------+--------------------------+
                                         |         |                          |                          |
                                         |         v                          v                          v
                                         |  +--------------------+     +--------------------+     +--------------------+
                                         |  | LOCAL REPO MCP     |     | GITHUB ISSUES MCP  |     | WEB RESEARCH MCP   |
                                         |  | (repo_server.py)   |     | (github_server.py) |     | (web_search_server)|
                                         |  | Files, Dirs, Deps  |     | Search Issues & PRs|     | Web Search & Fetch |
                                         |  +--------------------+     +--------------------+     +--------------------+
                                         |         |                          |                          |
                                         |         +--------------------------+--------------------------+
                                         |                                    |
                                         |                                    v
                                         |                  +------------------------------------+
                                         |                  | [8] TWO-STAGE EVIDENCE INGESTION   |
                                         |                  | Status: RETRIEVED -> VERIFIED Gate |
                                         |                  +------------------------------------+
                                         |                                    |
                                         |                                    v
                                         |                  +------------------------------------+
                                         |                  | [9] SINGLE-PASS REFLECTION ENGINE  |
                                         |                  | Contradictions, Fact vs Inference  |
                                         |                  +------------------------------------+
                                         |                                    |
                                         +-----------------+                  |
                                                           |                  |
                                                           v                  v
                                            +----------------------------------------------------+
                                            | [10] FINAL REPORT & TELEMETRY OBSERVABILITY        |
                                            | 6 Tabs: Report, Evidence, Sources, Matrix, Logs    |
                                            +----------------------------------------------------+
```

---

## 5. Model Context Protocol (MCP) Integration

This project implements a genuine **Model Context Protocol (MCP)** architecture:
- **Process Isolation**: Each MCP tool runs in a standalone Python subprocess communicating over standard input/output (`stdio`) via JSON-RPC 2.0.
- **Dynamic Tool Discovery**: The client manager initializes servers and discovers available tools using protocol methods (`initialize`, `tools/list`, `tools/call`).
- **High-Resolution Telemetry**: Captures exact wall-clock latency per individual tool invocation.
- **No In-Memory Mocking**: Zero fake Python function imports masquerading as MCP tools.

### MCP Tools Catalog

| Tool Name | MCP Server | Actions / Capabilities | Description |
|---|---|---|---|
| `inspect_local_repository` | `repo_server.py` | `list_dir`, `read_file`, `search_code`, `inspect_dependencies` | Inspects local files, directory trees, codebase text searches, and package manifests (`requirements.txt`, `pyproject.toml`). |
| `search_github_issues` | `github_server.py` | `query`, `repo` | Searches GitHub issues, PRs, and discussions via the GitHub REST API (with optional token & web fallback). |
| `search_web` | `web_search_server.py` | `query`, `max_results` | Performs DuckDuckGo web search with automated query cleaning and spam/domain filtering. |
| `fetch_web_document` | `web_search_server.py` | `url`, `max_chars` | Fetches and parses clean, text-extracted markdown from target URLs for grounded verification. |

---

## 6. Hybrid LLM Engine (Local Ollama & Cloud Groq)

The application supports both private local inference and high-speed cloud inference out of the box:

- **Local Inference (Ollama)**:
  - Default: `llama3.2:1b`, `llama3.2:latest`, `qwen3.5:2b-q4_K_M`, `qwen2.5`, `mistral`
  - 100% offline, zero API cost, complete privacy.
  - Built-in regex and JSON markdown extractors handle small-parameter output variances.
- **Cloud Inference (Groq LPUs)**:
  - Default models: `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `openai/gpt-oss-20b`
  - Ultra-fast token generation and low latency.
  - Seamlessly enabled by setting `GROQ_API_KEY` and `LLM_PROVIDER=groq` in `.env`.

---

## 7. Technology Stack

- **Runtime & Language**: Python 3.10+ (`asyncio`, `subprocess`, `pathlib`)
- **Data Validation & Schemas**: [Pydantic v2](https://docs.pydantic.dev/) (`BaseModel`, `Field`)
- **LLM Providers**:
  - [Ollama](https://ollama.com/) (Local inference via REST API)
  - [Groq](https://groq.com/) (High-throughput OpenAI-compatible API)
- **Tool Protocol**: Model Context Protocol (MCP JSON-RPC 2.0 Stdio)
- **Web UI & Observability**: [Streamlit](https://streamlit.io/) with custom styling, live logs, and metrics tables
- **Search & Retrieval**: `duckduckgo-search`, `beautifulsoup4`, GitHub REST API, `requests`, `httpx`
- **Testing**: `pytest`, `pytest-asyncio`

---

## 8. Installation & Setup

### 1. Prerequisites
- Python 3.10, 3.11, 3.12, or 3.13
- Either **Ollama** installed locally OR a **Groq API Key** (free tier available at [groq.com](https://console.groq.com/))

### 2. Clone the Repository
```bash
git clone https://github.com/your-org/ai-technical-research-investigator.git
cd ai-technical-research-investigator
```

### 3. Create a Virtual Environment and Install Dependencies
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 4. Configure Environment Variables (`.env`)
Create a `.env` file in the project root (or copy `.env.example`):

```bash
# Copy template
cp .env.example .env
```

Configure your `.env` settings:

```ini
# ==========================================
# LLM Provider Configuration
# ==========================================
# Options: 'groq' or 'ollama'
LLM_PROVIDER=groq

# Groq Cloud Settings (if LLM_PROVIDER=groq)
GROQ_API_KEY=your_groq_api_key_here
DEFAULT_MODEL=openai/gpt-oss-120b

# Ollama Local Settings (if LLM_PROVIDER=ollama)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest

# ==========================================
# Agent Investigation Settings
# ==========================================
MAX_ITERATIONS=12
MAX_MCP_CALLS=10
LLM_TEMPERATURE=0.1

# ==========================================
# External Service Tokens (Optional)
# ==========================================
GITHUB_TOKEN=
```

### 5. (Optional) Setup Local Ollama Models
If using local Ollama:
```bash
# Start Ollama daemon in your terminal:
ollama serve

# Pull your preferred model:
ollama pull llama3.2:1b
# or
ollama pull llama3.2
# or
ollama pull qwen2.5
```

---

## 9. Running the Application

Launch the Streamlit web dashboard:

```bash
streamlit run app/streamlit_app.py
```

Open your browser and navigate to: `http://localhost:8501`

### Dashboard Highlights
- **Preset Scenarios**: Quickly load real-world benchmark investigations from the sidebar dropdown.
- **Runtime Connectivity Card**: Displays live status of Groq/Ollama and discovered MCP tools.
- **Live Progress & Log Stream**: Real-time status updates and color-coded terminal log events during execution.
- **6-Tab Results Viewer**:
  1. 📋 **Investigation Report**: Grounded findings, root cause analysis, and actionable remediation steps.
  2. 🔍 **Grounded Evidence**: Cards detailing all gathered evidence items, verification badges, and reliability levels.
  3. 🌐 **Verified Sources**: Clickable web URLs and local file references.
  4. 📈 **Observability Matrix**: 14 empirical runtime metrics and 6 qualitative score cards (0–10).
  5. 🛠️ **Agent Activity & Traces**: Step-by-step ReAct thought, action, and observation timeline.
  6. 📜 **Technical Execution Logs**: Authoritative timestamped log stream.

---

## 10. Demonstration Scenarios

The system includes 5 pre-configured demonstration scenarios:

| Scenario | Mode | Sample Query / Target | Expected Behavior |
|---|---|---|---|
| **Scenario 1: Direct Technical Question** | Direct Synthesis | *"What is Python Global Interpreter Lock (GIL) and how does free-threading mode in Python 3.13 change it?"* | Classifies intent as general knowledge, synthesizes response directly with **zero MCP tool calls**, executes 1-pass reflection. |
| **Scenario 2: Technical Compatibility Research** | Web & GitHub MCP | *"Why does FastAPI raise PydanticUserError for @validator after migrating from Pydantic v1 to Pydantic v2?"* | Invokes `search_web` and `search_github_issues`, identifies the migration to `@field_validator(mode=...)`, extracts docs, and verifies root cause. |
| **Scenario 3: Local Repo Investigation** | Repo & Manifest MCP | *"Why is my FastAPI application failing after upgrading Pydantic from version 1 to version 2?"* (`data/sample_project`) | Validates local directory, inspects `requirements.txt` and `app/models.py`, correlates local code with external Pydantic v2 migration rules. |
| **Scenario 4: Conflicting Community Evidence** | Multi-Source Reflection | *"Is Python 3.14 officially released and recommended for production use as of today?"* | Detects pre-release vs stable differences across sources, records discrepancies in the Reflection Engine, and warns against production use. |
| **Scenario 5: Insufficient Evidence Handling** | Safe Failure Boundary | *"Why did proprietary internal module 'lib-quantum-core-x99' crash inside cluster node cluster-omega-42?"* | Searches for nonexistent terms, refuses to hallucinate root causes, returns a clear **INSUFFICIENT EVIDENCE** report with 0% false confidence. |

---

## 11. Observability & Telemetry Framework

Every investigation automatically records 14 empirical telemetry parameters:

1. **Total Investigation Time**: Measured wall-clock duration (`time.time()`).
2. **Total LLM Calls**: Number of completions sent to Ollama or Groq.
3. **Average LLM Latency**: Mean duration per LLM generation step.
4. **Total Tokens**: Exact prompt and generation token counts.
5. **Total MCP Tool Calls**: Cumulative count of stdio tool invocations.
6. **Successful vs Failed Tool Calls**: Differentiated via stdio exit codes and error payloads.
7. **Duplicate Calls Prevented**: In-memory cache hits preventing redundant network requests.
8. **Average Tool Latency**: Subprocess invocation and JSON-RPC round-trip latency.
9. **Web Searches Executed**: Counter for `search_web` invocations.
10. **GitHub Searches Executed**: Counter for `search_github_issues` invocations.
11. **Local Repo Inspections**: Counter for `inspect_local_repository` invocations.
12. **Web Documents Fetched**: Counter for `fetch_web_document` invocations.
13. **Evidence Items Collected**: Count of distinct findings ingested into the Evidence Store.
14. **Final Confidence Rating**: Percentage (0%–100%) calculated by the Reflection Engine.

### Qualitative Assessment Scores (0.0 – 10.0)
- **Evidence Completeness**: Proportion of required evidence categories verified.
- **Source Quality**: Weighted average based on source authority (`HIGH`, `MEDIUM`, `LOW`).
- **Answer Relevance**: Grounding score of the final synthesis against the initial query.
- **Reasoning Sufficiency**: Depth of ReAct iteration steps and logical linkages.
- **Tool Selection Efficiency**: Ratio of useful tool calls versus redundant or failed calls.
- **Contradiction Detection**: Explicit verification flag from single-pass reflection.

---

## 12. Project Structure

```text
ai-technical-research-investigator/
├── .env.example                    # Template for environment configuration
├── .gitignore                      # Git ignore patterns
├── README.md                       # Comprehensive project documentation
├── requirements.txt                # Python package dependencies
├── run_tests.py                    # Standalone test runner script
├── docs/                           # In-depth architectural & design specifications
│   ├── ARCHITECTURE.md             # End-to-end system architecture & sequence diagrams
│   ├── DECISIONS.md                # Architecture Decision Records (ADRs 001–008)
│   ├── EVALUATION.md               # Telemetry metrics and qualitative scoring algorithms
│   └── MCP_TOOLS.md                # Detailed MCP stdio JSON-RPC tool specification
├── app/
│   ├── streamlit_app.py            # Streamlit interactive UI dashboard
│   ├── agent/
│   │   ├── agent.py                # Main orchestrator & investigation execution loop
│   │   ├── planner.py              # ReAct planner, query classifier & decision logic
│   │   ├── prompts.py              # System prompts & JSON templates
│   │   ├── reflection.py           # Single-pass reflection engine & contradiction detector
│   │   └── state.py                # Agent state tracking & iteration history
│   ├── mcp/
│   │   ├── client.py               # MCP client manager & stdio subprocess controller
│   │   ├── protocol.py             # MCP JSON-RPC 2.0 message schemas & base server
│   │   └── servers/
│   │       ├── github_server.py    # GitHub issues & PR research MCP server
│   │       ├── repo_server.py      # Local codebase & manifest inspection MCP server
│   │       └── web_search_server.py# Web search & full document retrieval MCP server
│   ├── llm/
│   │   ├── groq_client.py          # High-throughput Groq cloud LLM client
│   │   ├── ollama_client.py        # Local Ollama LLM client
│   │   └── models.py               # LLM message data models & request types
│   ├── evidence/
│   │   ├── manager.py              # Two-stage evidence store, parser & deduplicator
│   │   └── models.py               # Evidence item schemas, source types & reliability levels
│   ├── evaluation/
│   │   ├── evaluator.py            # Qualitative scoring engine (0-10 scale)
│   │   ├── metrics.py              # Investigation telemetry data models
│   │   └── tracker.py              # Real-time latency & counter tracker
│   └── logging/
│       └── logger.py               # Structured log event dispatcher & categories
├── tests/
│   ├── test_agent.py               # Agent initialization and basic routing tests
│   ├── test_evaluation.py          # Telemetry tracking & matrix calculation tests
│   ├── test_evidence.py            # Evidence ingestion, deduplication & status tests
│   ├── test_mcp.py                 # MCP stdio protocol & server execution tests
│   ├── test_ollama.py              # Ollama client and JSON extraction tests
│   ├── test_reflection.py          # Reflection engine & contradiction checking tests
│   ├── test_regressions.py         # Regression tests for boundary validation & routing
│   └── test_scenarios.py           # End-to-end tests for all 5 demonstration scenarios
└── data/
    └── sample_project/             # Sample FastAPI project for Scenario 3 testing
        ├── README.md               # Sample project notes
        ├── requirements.txt        # Sample dependencies (Pydantic v2 conflict)
        ├── error_log.txt           # Sample startup traceback
        └── app/
            ├── main.py             # FastAPI entry point
            └── models.py           # Deprecated @validator usage
```

---

## 13. Testing

Run the automated test suite with `pytest`:

```bash
# Run all tests with verbose output
python -m pytest -v

# Run a specific test module
python -m pytest tests/test_regressions.py -v
python -m pytest tests/test_mcp.py -v
python -m pytest tests/test_evidence.py -v

# Run the standalone end-to-end investigation runner
python run_tests.py
```

---

## 14. Documentation Index

For in-depth technical specifications, please consult the dedicated documentation in the `docs/` folder:

- **[System Architecture (ARCHITECTURE.md)](docs/ARCHITECTURE.md)**: Full component interaction lifecycle, sequence diagrams, and failure modes.
- **[Architecture Decisions (DECISIONS.md)](docs/DECISIONS.md)**: Formal ADRs (ADR-001 through ADR-008) covering hybrid LLMs, MCP stdio isolation, two-stage evidence gates, and reflection guardrails.
- **[Evaluation Framework (EVALUATION.md)](docs/EVALUATION.md)**: Complete mathematical formulas for all 14 empirical metrics and 6 qualitative scores.
- **[MCP Tools Reference (MCP_TOOLS.md)](docs/MCP_TOOLS.md)**: Full JSON-RPC 2.0 schemas, parameter requirements, and sample payloads for all tools.

---

## 15. Guardrails & Runtime Boundaries

- **Repository Path Validation**: Local repository paths are strictly validated before starting an investigation. Invalid paths are rejected immediately with a descriptive error.
- **Evidence vs Search Hits**: Search engine snippets are cataloged with status `RETRIEVED` and are not treated as verified facts until full content is fetched and cross-checked (`VERIFIED`).
- **Resilience to External Outages**: Network, GitHub, DuckDuckGo, or LLM connection issues are captured in runtime telemetry; the investigator emits a conservative insufficient-evidence report rather than fabricating an answer.
- **Loop Protection**: Strict upper bounds on iterations (`MAX_ITERATIONS`) and tool invocations (`MAX_MCP_CALLS`) prevent runaway loops.

---

## 16. License

This project is licensed under the [MIT License](LICENSE).
