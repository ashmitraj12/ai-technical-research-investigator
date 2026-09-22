# Architecture Decision Records (ADRs) — AI Technical Research Investigator

This document records the foundational architectural decisions, rationale, and trade-offs made during the design and implementation of the **AI Technical Research Investigator**.

---

## ADR Index

| ADR ID | Title | Status | Date |
| :--- | :--- | :--- | :--- |
| **ADR-001** | [Hybrid LLM Engine (Local Ollama & High-Throughput Cloud Groq)](#adr-001-hybrid-llm-engine-local-ollama--high-throughput-cloud-groq) | **Accepted** | 2026-08-23 |
| **ADR-002** | [Native Process-Isolated Stdio Model Context Protocol (MCP)](#adr-002-native-process-isolated-stdio-model-context-protocol-mcp) | **Accepted** | 2026-08-23 |
| **ADR-003** | [Intent Pre-Flight Classification & Zero-Tool Fast-Path](#adr-003-intent-pre-flight-classification--zero-tool-fast-path) | **Accepted** | 2026-08-24 |
| **ADR-004** | [Boundary Repository Path Validation & Safe Failure Handling](#adr-004-boundary-repository-path-validation--safe-failure-handling) | **Accepted** | 2026-08-24 |
| **ADR-005** | [Two-Stage Evidence Ingestion Gate (RETRIEVED vs VERIFIED)](#adr-005-two-stage-evidence-ingestion-gate-retrieved-vs-verified) | **Accepted** | 2026-08-25 |
| **ADR-006** | [Single-Pass Reflection Guardrail with Strict Loop Termination](#adr-006-single-pass-reflection-guardrail-with-strict-loop-termination) | **Accepted** | 2026-08-25 |
| **ADR-007** | [Thread-Safe Asynchronous Observability & Logging Sink](#adr-007-thread-safe-asynchronous-observability--logging-sink) | **Accepted** | 2026-08-26 |
| **ADR-008** | [Empirical Telemetry & Grounded Qualitative Scoring (0.0–10.0)](#adr-008-empirical-telemetry--grounded-qualitative-scoring-00100) | **Accepted** | 2026-08-26 |

---

## ADR-001: Hybrid LLM Engine (Local Ollama & High-Throughput Cloud Groq)

### Context & Problem Statement
The system requires an LLM orchestration layer capable of structured JSON generation, tool selection, and grounded report synthesis. It must support zero-cost local private execution (Ollama) while seamlessly supporting high-throughput cloud inference (Groq) for rapid automated testing and low-latency production workflows.

### Decision
Implement an abstract client interface with dual concrete drivers:
1. **`OllamaClient`** (`app/llm/ollama_client.py`): Connects to local Ollama daemon (port 11434) supporting `llama3.2:1b`, `llama3.2:latest`, `qwen2.5`, and `mistral`.
2. **`GroqClient`** (`app/llm/groq_client.py`): Connects to Groq cloud API utilizing high-speed LPUs with models like `llama-3.3-70b-versatile` and `llama3-8b-8192`.

### Consequences & Trade-offs
- **Positive**: Zero vendor lock-in; complete privacy when running locally; ultra-fast benchmarking with cloud providers.
- **Negative**: Local small parameter models (1B–3B) require robust JSON markdown parsers and schema auto-correction to handle occasionally malformed JSON.

---

## ADR-002: Native Process-Isolated Stdio Model Context Protocol (MCP)

### Context & Problem Statement
Tool execution must conform to the open **Model Context Protocol (MCP)** JSON-RPC 2.0 specification. The architecture must guarantee process isolation, security boundaries, and modular tool servers without hardcoded in-memory Python function imports.

### Decision
Implement native stdio-based MCP servers (`app/mcp/servers/`) managed by a central client manager (`app/mcp/client.py`):
1. **`repo_server.py`**: Local repository, file inspection, and dependency tree parsing.
2. **`github_server.py`**: GitHub REST API issues, PRs, and community discussions.
3. **`web_search_server.py`**: DuckDuckGo web search and full document HTML-to-markdown extraction.

### Consequences & Trade-offs
- **Positive**: Complete process isolation; crashes in external search or web scraping cannot terminate the core agent process; strict JSON-RPC protocol compliance.
- **Negative**: Subprocess IPC introduces minor stdio serialization overhead (~50–150ms per call), which is tracked explicitly in runtime telemetry.

---

## ADR-003: Intent Pre-Flight Classification & Zero-Tool Fast-Path

### Context & Problem Statement
Not every user prompt requires web searches or codebase inspections (e.g., conceptual questions like *"What is Python GIL?"* or syntax comparisons). Invoking MCP tools unnecessarily causes tool-call bloat, excessive latency, and token waste.

### Decision
Introduce a pre-flight **Strategic Query Classifier** (`QUERY_CLASSIFICATION_PROMPT` in `app/agent/prompts.py`) before entering the ReAct loop:
- Classifies queries into `GENERAL_KNOWLEDGE` (conceptual, stable facts) or `INVESTIGATION_REQUIRED` (bugs, version incompatibilities, repository errors).
- For `GENERAL_KNOWLEDGE`, bypasses the ReAct tool loop entirely and routes directly to synthesis with **zero MCP tool calls** and 1 reflection pass.

### Consequences & Trade-offs
- **Positive**: Conceptual questions resolve in <2 seconds with 100% tool selection efficiency; saves external API calls and token budgets.
- **Negative**: Classifier prompt must be concise and strictly calibrated to avoid false negatives on ambiguous bug descriptions.

---

## ADR-004: Boundary Repository Path Validation & Safe Failure Handling

### Context & Problem Statement
When users provide invalid, non-existent, or unreadable repository paths, the agent should not trigger hallucinated file searches or invent fictitious local directory structures.

### Decision
Enforce strict pre-flight path validation at the public controller boundary (`app/agent/agent.py`):
- If a provided path does not exist on disk, the agent halts before initiating MCP tool loops, marks the state as invalid, and returns an explicit, structured `INSUFFICIENT_EVIDENCE` or error report.
- Local repository tool calls are restricted to the validated workspace root to prevent directory traversal attacks.

### Consequences & Trade-offs
- **Positive**: Eliminates hallucinated codebase findings; prevents unauthorized filesystem traversal; fails fast and transparently.

---

## ADR-005: Two-Stage Evidence Ingestion Gate (RETRIEVED vs VERIFIED)

### Context & Problem Statement
Search engine snippet hits often contain outdated blog posts, speculative forum answers, or misleading headlines. Treating every search result as verified ground truth produces hallucinations.

### Decision
Implement a two-stage evidence lifecycle in `app/evidence/manager.py`:
1. **`RETRIEVED`**: Search hits (`search_web`, `search_github_issues`) are registered as candidate sources only.
2. **`VERIFIED`**: Evidence is promoted to `VERIFIED` only after full document extraction (`fetch_web_document`), authoritative documentation cross-referencing, or direct local file content verification (`inspect_local_repository`).

```mermaid
flowchart LR
    S[Search Query] --> R["Stage 1: RETRIEVED (Candidate URL/Snippet)"]
    R --> F[fetch_web_document / read_file]
    F --> V["Stage 2: VERIFIED (Grounded Finding)"]
    V --> E[Evidence Manager Store]
```

### Consequences & Trade-offs
- **Positive**: Drastically improves report factual accuracy; prevents snippet-based hallucination.
- **Negative**: Requires secondary fetch operations, slightly increasing total investigation duration for web research.

---

## ADR-006: Single-Pass Reflection Guardrail with Strict Loop Termination

### Context & Problem Statement
Iterative self-reflection in agentic frameworks frequently suffers from two failure modes:
1. Infinite or runaway reflection loops that drain token budgets.
2. Unchecked hallucination where the agent invents unsupported recommendations.

### Decision
Enforce a **deterministic single-pass reflection engine** (`app/agent/reflection.py`):
- Exactly **ONE** reflection pass executes after evidence gathering and before final synthesis.
- The reflection engine evaluates verified evidence items, separates facts from inferences, checks for contradictions, and outputs a grounded confidence percentage (0%–100%).
- Loop termination is bounded by `max_iterations`, `max_mcp_calls`, or when the ReAct planner emits `action: "finish"`.

### Consequences & Trade-offs
- **Positive**: Guaranteed termination; predictable latency; strictly audited confidence scores.

---

## ADR-007: Thread-Safe Asynchronous Observability & Logging Sink

### Context & Problem Statement
During async agent execution in Streamlit, real-time logging, step-by-step thoughts, and MCP tool execution metrics must be streamed to the UI without blocking the computational thread or crashing the web interface.

### Decision
Build a thread-safe Queue-based Event Logger sink (`app/logging/logger.py`) integrated with Streamlit callbacks:
- Emits structured event records (`timestamp`, `level`, `component`, `message`, `metadata`).
- Separates user-facing status indicators from internal debug telemetry.

### Consequences & Trade-offs
- **Positive**: Rich real-time progress bars, live log terminal, and detailed inspection tabs in Streamlit without UI stutter.

---

## ADR-008: Empirical Telemetry & Grounded Qualitative Scoring (0.0–10.0)

### Context & Problem Statement
Evaluation must not rely on subjective LLM-judged fluff. It must be computed from actual runtime telemetry (wall-clock timers, token counters, stdio error codes) and verifiable evidence coverage.

### Decision
Implement `EvaluationEngine` (`app/evaluation/evaluator.py`) producing:
1. **Evaluation Matrix (14 Runtime Metrics)**: Wall-clock time, LLM latencies, tokens, MCP tool counts, duplicate call prevention, error count.
2. **6 Qualitative Dimensions (0.0–10.0 Score)**: Evidence Completeness, Source Quality, Answer Relevance, Reasoning Sufficiency, Tool Selection Efficiency, and Contradiction Detection.

### Consequences & Trade-offs
- **Positive**: Transparent, reproducible, and verifiable scoring across all test scenarios.
