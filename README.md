# fiware-mcp-client

Small FIWARE MCP client and agent orchestration CLI for querying a FIWARE NGSI-LD Context Broker through OpenAI models.

The project is YAML-first and organized around a thin CLI, application services, validated Pydantic contracts, backend adapters, and a normalized `RunResult` used by run, chat, eval, and benchmark flows.

## Capabilities

- Single-turn runs with the OpenAI Responses API compatibility backend.
- OpenAI Agents SDK backend with local MCP transports, SQLite chat sessions, streaming, and optional handoff configuration.
- YAML profile and tool catalog configuration.
- Backend-neutral tool specs with backend-specific adapters.
- Evaluation modes: exact text, JSON equality, JSON subset, regex, and LLM-as-judge.
- CSV benchmarks using the same `RunService` pipeline as normal runs.

## Requirements

- Python 3.10+
- OpenAI API key
- MCP server exposing FIWARE tools such as `execute_query`, `get_entity_types`, `CB_version`, and `haversine_dist`

References used by this academic project:

- FIWARE MCP server: https://github.com/dncampo/FIWARE-MCP-Server
- Context broker data loader: https://github.com/jason-fox/Context-Data-Loader

## Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -r requirements.txt
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `.template.env` to `.env` and set:

```text
OPENAI_API_KEY=...
```

Copy `config.example.yaml` to `config.yaml` and edit the YAML defaults:

```yaml
profiles_yaml: app/profiles/fiware-agents.yaml
tools_yaml: app/tools/tools.yaml
agent_id: fiware-client

read_only: true
prompts_dir: prompts
log_level: DEBUG
log_to_file: true
logs_dir: logs
```

Use `agent_id: fiware-client` for the Responses compatibility profile. Use `agent_id: fiware-client-agents-local` for the OpenAI Agents SDK profile with local streamable HTTP MCP at `http://127.0.0.1:5001/mcp`.

## Profiles

Profiles live in `app/profiles/fiware-agents.yaml`. Each profile selects a system prompt, backend, tools, and optional handoffs:

```yaml
default_agent: fiware-client

agents:
  - id: fiware-client-agents-local
    description: NGSI-LD expert assistant using the OpenAI Agents SDK
    system_prompt: system2.3.md
    backend:
      type: openai_agents
      model_name: gpt-5.2
      session:
        enabled: true
        provider: sqlite
        path: data/sessions.sqlite
    tools: [fiware-mcp-local]
    handoffs: []

  - id: fiware-evaluator
    description: LLM judge for evaluation and benchmarks
    system_prompt: judge_system.md
    backend:
      type: openai_responses
      model_name: gpt-5-nano
    tools: []
```

The evaluator is a normal configured agent. Evaluation code calls it through the same service layer instead of using a separate provider path.

## Tools

Tools live in `app/tools/tools.yaml` and are referenced by profile name:

```yaml
tools_definitions:
  - name: fiware-mcp
    type: mcp_hosted
    config:
      server_label: fiware-mcp
      server_url: https://example.com/mcp
      allowed_tools: execute_query, get_entity_types, CB_version

  - name: fiware-mcp-local
    type: mcp_streamable_http
    config:
      name: fiware-mcp
      url: http://127.0.0.1:5001/mcp
      allowed_tools: execute_query, get_entity_types, CB_version
      cache_tools_list: true
```

Supported tool categories include `mcp_hosted`, `mcp_streamable_http`, `mcp_sse`, `mcp_stdio`, `openai_hosted_tool`, and reserved `function_tool`. Legacy `type: mcp` is still accepted as an alias for `mcp_hosted`.

## CLI Usage

All commands accept `--config`, defaulting to `config.yaml`:

```powershell
python -m app.cli <command> --config config.yaml
```

### Single Run

```powershell
python -m app.cli run --prompt "List available entity types"
```

Useful overrides:

```powershell
python -m app.cli run --prompt "List entity types" --agent-id fiware-client-agents-local
python -m app.cli run --prompt "Remember this parcel id: urn:ngsi-ld:AgriParcel:005" --agent-id fiware-client-agents-local --session-id demo-session
```

`run --session-id` is a low-level hook for Agents SDK session memory. For normal multi-turn work, prefer `chat`.

### Chat

Interactive chat uses a persistent `session_id` and the same configured agent/profile defaults as `run`:

```powershell
python -m app.cli chat --agent-id fiware-client-agents-local --session-id demo-session
```

Send one chat turn and exit:

```powershell
python -m app.cli chat --prompt "What did I ask before?" --agent-id fiware-client-agents-local --session-id demo-session
```

Stream text deltas with the Agents SDK backend:

```powershell
python -m app.cli chat --stream --agent-id fiware-client-agents-local --session-id demo-session
```

The Responses backend remains available for compatibility, but it does not provide SDK session memory or streaming.

### Evaluation

```powershell
python -m app.cli eval --prompt "ping" --exact-text "OK"
python -m app.cli eval --prompt "..." --equals-json '{ "status": 200 }'
python -m app.cli eval --prompt "..." --json-subset '{ "status": 200 }'
python -m app.cli eval --prompt "..." --regex "status\\D+200"
```

LLM-as-judge expects a JSON file:

```powershell
python -m app.cli eval --prompt "How many animals are located at AgriParcel 005?" --llm-judge-file judge.json
```

Judge file shape:

```json
{
  "gold": {
    "numeric": 13,
    "queries": ["/ngsi-ld/v1/entities?type=Animal&q=locatedAt==%22urn:ngsi-ld:AgriParcel:005%22&count=true"]
  },
  "weights": {"correctness": 0.7, "reasoning": 0.2, "efficiency": 0.1},
  "pass_threshold": 0.8,
  "grading_mode": "gated",
  "min_correctness": 1.0
}
```

## Benchmarks

Run benchmark CSV files:

```powershell
python -m app.cli bench --csv benchmark/benchmark_tests.csv --out bench_out
python -m app.cli bench --csv benchmark/benchmark_tests.csv --out "bench_out/results-v2.csv"
```

Benchmark rows can select `profiles_yaml` and `agent_id`; otherwise CLI/config defaults are used. Output includes model, response text, evaluation verdicts, score fields, MCP call count, and extracted queries.

Important CSV columns:

- `id`: benchmark identifier
- `question`: user prompt
- `model`: legacy-mode model override
- `system_prompt_file`: legacy-mode prompt override
- `profiles_yaml`: YAML profiles path
- `agent_id`: profile agent id
- `eval_mode`: `exact_text`, `equals_json`, `json_subset`, `regex`, `llm_judge`, or empty
- `expected`: expected value or judge JSON payload

## Architecture

Current high-level layers:

- `app/cli.py`: argument parsing and output rendering only.
- `app/services/run_service.py`: single-turn orchestration and normalized `RunResult`.
- `app/services/chat_service.py`: persistent chat turns over `RunService`.
- `app/core/config.py` and `app/core/config_loader.py`: Pydantic config models, YAML loading, env placeholders, and legacy compatibility.
- `app/core/agent_session.py`: configured agent registry and routing.
- `app/backends/openai_responses_backend.py`: direct Responses API compatibility backend.
- `app/backends/openai_agents_backend.py`: Agents SDK backend with local MCP, SQLite sessions, streaming, and handoffs.
- `app/tools/*_adapter.py`: backend-specific conversion from neutral `ToolSpec`.
- `app/core/normalizers.py`: provider-agnostic output and MCP trace extraction.
- `app/evaluator/evaluator.py` and `benchmark/csv_runner.py`: evaluation and benchmark flows over normalized results.

The stable result contract is `RunResult`. Evaluation and benchmark code should not inspect raw OpenAI response objects directly.

## Development

Run tests:

```powershell
.\.venv\Scripts\python -m pytest -q
```

Compile check:

```powershell
.\.venv\Scripts\python -m compileall app tests benchmark
```

## Notes

- Do not commit `.env` or API keys.
- Local Agents SDK MCP profile assumes a streamable HTTP MCP server at `http://127.0.0.1:5001/mcp`.
- Use explicit `handoffs: []` or a list of agent ids in profiles. Handoff targets must currently use the `openai_agents` backend.
- `read_only` is appended to prompts and is intended to become stricter tool filtering or approval policy as guardrails mature.

## License

This project is licensed under the Apache License 2.0.
