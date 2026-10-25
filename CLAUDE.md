# SafeSpeak

Multi-agent system that analyses a suspicious message (scam / phishing) and
returns a plain-language verdict: is it fraudulent, why, and what to do next.
University project — code must stay small and easy to explain in a viva.

## Hard constraints (course rules — do not deviate)

- **Frameworks:** Google ADK and CrewAI only. No LangChain, LangGraph, AutoGen.
  (LiteLLM is used only as ADK's built-in model adapter for Ollama.)
- **ADK** runs the live detection service. **CrewAI** runs offline background crews.
- **Blackboard:** agents coordinate through one `CaseRecord` in ADK session
  state. Agents never message each other directly.
- **Tools:** all exposed through the custom MCP server in `safespeak/mcp_server/`,
  never imported directly by agents.
- **Typed I/O:** every agent input/output is a Pydantic model from
  `safespeak/schemas.py`. No free-text passing.
- **Guardrails:** ADK callbacks (before/after model, tool, agent), not prompt text.
- **LLM:** local Ollama only (messages contain OTPs and account references).
- **Logging:** every agent/model/tool call logged for tracing and cost/latency.

## Live pipeline (ADK, 9 agents)

```
Input guardrail
  -> Coordinator (opens case)
  -> Intake/Parser
  -> Coordinator (routes conditionally)
  -> specialists: Verifier | Pattern | Retrieval | Correlation
  -> Reasoner (verdict + confidence)
  -> Explainer <-> Critic
  -> Output guardrail
  -> final verdict
```

Two capped loops, caps enforced in `before_agent` callbacks (not prompts):
- Reasoner -> Coordinator: max `MAX_REASONER_LOOPS` (2)
- Critic -> Explainer: max `MAX_CRITIC_LOOPS` (2)

## Layout

| Path | Purpose |
|---|---|
| `safespeak/schemas.py` | All Pydantic models, incl. `CaseRecord` and loop caps |
| `safespeak/blackboard.py` | Typed read/write helpers for the case in session state |
| `safespeak/config.py` | Env settings (model, Ollama URL, log path) |
| `safespeak/app.py` | Builds the agent tree; `analyse(text) -> AnalysisResult` |
| `safespeak/__main__.py` | CLI: `python -m safespeak "message"` |
| `safespeak/render.py` | Verdict + Explanation -> final Markdown |
| `safespeak/agents/common.py` | `make_llm_agent()`, `state_event()`, model factory |
| `safespeak/agents/coordinator.py` | Root agent: runs the pipeline, retry-on-invalid-output |
| `safespeak/agents/router.py` | Coordinator's routing step (rule-based), carries the loop cap |
| `safespeak/agents/{parser,reasoner,explainer,critic}.py` | LLM agents with an `output_schema` |
| `safespeak/agents/verifier.py` | LLM agent that calls the two MCP tools; findings built from tool results |
| `safespeak/agents/specialists.py` | STUBS for Pattern, Retrieval, Correlation (empty results) |
| `safespeak/guardrails/input_guard.py` | before_agent on Coordinator: block, redact, flag |
| `safespeak/guardrails/model_guard.py` | before_model: strip chat turns, re-redact |
| `safespeak/guardrails/loop_caps.py` | before_agent caps: Router (Reasoner loop), Explainer (Critic loop) |
| `safespeak/guardrails/output_guard.py` | after_agent on Coordinator: safe advice, render, close |
| `safespeak/guardrails/redaction.py` | OTP/card/account/Aadhaar masking regexes |
| `safespeak/observability/tracer.py` | JSONL trace + RunMetrics |
| `safespeak/evaluate.py` | Evaluation harness: N messages from a CSV -> results/*.csv |
| `safespeak/mcp_server/server.py` | Our MCP server (stdio): `domain_age`, `domain_reputation` |
| `safespeak/mcp_server/whois_tool.py` | Tool 1: domain age via RDAP (WHOIS successor) |
| `safespeak/mcp_server/reputation_tool.py` | Tool 2: OpenPhish + Phishing.Database blocklists, brand lookalike |
| `safespeak/mcp_server/{domains,cache}.py` | Domain parsing (offline suffix list), TTL file cache |
| `safespeak/crews/` | CrewAI offline crews (later pass) |
| `data/` | Datasets (see Data rules); `data/cache/` = tool cache (git-ignored) |
| `tests/` | pytest; `fake_llm.py` scripted model, `conftest.py` offline tool cache |

## Blackboard rules

- State key: `"case"` (`blackboard.CASE_KEY`), stored as a JSON dict.
- Read with `read_case(state)`; write with `post(state, section, model, status)`.
- Always write through `post()` — it re-validates the whole record and
  re-assigns the key so ADK records the state delta.
- `case_id`, `created_at`, `message_text` are read-only after `open_case()`.
- Only redacted text is ever stored in the case.
- LLM agents get a typed input model (`ParserInput`, `VerifierInput`,
  `ReasonerInput`, `ExplainerInput`, `CriticInput`) built from the case; the model guard removes ADK's chat
  turns, so the case is their only input. Raw output goes to a `temp:` key,
  then `post_output` validates it and posts it to the case.
- Custom (non-LLM) agents write state via `state_event()` so the delta is
  carried in an Event and persisted.

## Retry and loop rules

- Invalid LLM output: Coordinator retries once (`MAX_VALIDATION_RETRIES`),
  logs a `GuardrailEvent` ("retried"/"failed"), then raises `SchemaViolation`.
- Loop caps live only in `guardrails/loop_caps.py`:
  `cap_reasoner_loops` on the Router, `cap_critic_loops` on the Explainer.
  At the cap the callback appends to `case.capped_loops`, logs a
  GuardrailEvent and skips the agent; the Coordinator reads `capped_loops`.
  Verdicts/critiques are not edited, so the record stays truthful.
- A skipped LlmAgent's returned content is validated by ADK against its
  output_schema, so the Explainer's veto returns its last accepted draft.

## MCP tools (exactly two; do not add more without asking)

- Agents reach tools only via `McpToolset` -> `python -m safespeak.mcp_server`.
- Both tools return a `VerifierFinding` as MCP structured content.
- Verifier callbacks: `record_finding` (after_tool) validates and posts each
  result; ignores tools called on domains not in the message.
  `fill_unchecked` (after_agent) marks skipped checks `unknown`.
  `skip_if_no_domains` (before_agent) avoids an LLM call with nothing to check.
- Only the domain name leaves the machine (RDAP); feeds are downloaded and
  matched locally. Cache TTLs in `config.py`.

## Data rules

- `test_real.csv` (463, real, English): ALL reported numbers come from it.
  Never tune prompts/rules on it, never read it while developing.
- `dev_synthetic.csv` (2737): development and tuning.
- `hard_negatives_synthetic.csv` (3433, all legitimate): robustness, reported
  separately, never merged into headline metrics.
- Do NOT reintroduce sender_id / sender_type / timestamp from the original
  Kaggle A2P file (sender IDs were randomly assigned). Sender-ID validation,
  when built, must use TRAI header rules only.
- Results CSVs never contain message text.
- Known gaps: no Hinglish test data; hard negatives synthetic; no RAG corpus.

## Tracing

`logs/trace.jsonl`, one record per agent/model/tool call plus one `run`
record with `RunMetrics`. Agent records' `output` = case sections changed.
Callback order: tracer first, then guardrails (a guardrail returning content
stops later callbacks).

## Build status

- [x] Step 1: repo structure, this file
- [x] Step 2: Pydantic models
- [x] Step 3: blackboard helpers
- [x] Step 4: minimal path (guardrail -> Coordinator -> Parser -> Reasoner -> Explainer -> guardrail), specialists stubbed, Markdown output
- [x] Step 5: structured logging of every agent call (+ RunMetrics)
- [x] MCP server (2 tools) + real Verifier
- [x] Critic agent + capped Explainer <-> Critic loop
- [x] Evaluation harness (`safespeak.evaluate`) + `--json` CLI flag
- [ ] Real Pattern, Retrieval (RAG), Correlation specialists
- [ ] Phase 3 (deferred, do not start): CrewAI crews, A2A, cloud deploy,
      architecture comparison, 40-run benchmark

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q            # offline, uses tests/fake_llm.py
ollama pull qwen3:8b        # default model; override with SAFESPEAK_MODEL=ollama_chat/qwen2.5:7b
.venv/bin/python -m safespeak "your message here"
.venv/bin/python -m safespeak --json "your message here"   # CaseRecord as JSON
.venv/bin/python -m safespeak.evaluate --file data/dev_synthetic.csv --n 10
.venv/bin/python -m safespeak.mcp_server      # run the MCP server alone (stdio)
```

## Code style

Small functions, one job each, docstring saying why. Prefer plain code over
clever code — the author must explain and modify it live.
