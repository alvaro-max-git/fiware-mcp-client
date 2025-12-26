# fiware-mcp-client

Client that queries a FIWARE NGSI-LD Context Broker via an MCP server using an OpenAI model. It supports single runs and response evaluation.

- CLI: app/cli.py
- Config: app/core/config.py (+ config.yaml)
- Runner: app/core/runner.py
- Evaluator: app/evaluator/evaluator.py
- Types: app/core/types.py
- Prompts: prompts/

## Requirements

- Python 3.10+
- An MCP server exposing tools (e.g., execute_query, get_entity_types, CB_version) pointing to your Context Broker.

Right now using:
- Server: https://github.com/dncampo/FIWARE-MCP-Server
- Context-broker: https://github.com/jason-fox/Context-Data-Loader

## Installation

Create a virtual environment and install dependencies:
- Windows (PowerShell)
  - python -m venv .venv
  - .\.venv\Scripts\Activate
- macOS/Linux (bash)
  - python3 -m venv .venv
  - source .venv/bin/activate

Install:
- pip install -r requirements.txt

## Configuration

This project is **YAML-first**.

1) **Secrets & environment** (local, do not commit):
- Copy `.template.env` to `.env` and set at least:
  - `OPENAI_API_KEY=...`

2) **Runtime config** (`config.yaml`, local per use-case):
- Copy `config.example.yaml` to `config.yaml` and edit:
  - `profiles_yaml`: agent profiles (YAML)
  - `tools_yaml`: tool catalog (YAML)
  - `agent_id`: default agent
  - `mcp_servers`: MCP servers for legacy env-only mode

### YAML-mode (recommended)

In YAML-mode (when `profiles_yaml` is set), tools are loaded from the tools catalog YAML.
There is **no fallback** to MCP servers defined in `.env`.

### Legacy env-only mode (compat)

If you run without `profiles_yaml`, the client uses the legacy path (OpenAI Responses directly) and MCP servers are configured via `config.yaml` (`mcp_servers`).

Optional backward-compat (not recommended): you can still configure MCP servers via `.env`.

Multiple MCP servers (optional):
- Use `MCP0_LABEL`, `MCP0_URL`, `MCP0_ALLOWED_TOOLS`, then `MCP1_...`, etc.

## Usage

Run the CLI:
- python -m app.cli <command> [options]

System prompt selection:
- Defaults to `config.yaml` (`system_prompt_file`) in legacy mode.
- Override per run with --system-prompt-file.

### Single run

- Example:
  - Windows (PowerShell):
    - python -m app.cli run --prompt "List available entity types"
  - macOS/Linux (bash):
    - python -m app.cli run --prompt 'List available entity types'

Prints the LLM output.

### Evaluation mode

Compare the LLM response against an expected value using one criterion:
- --exact-text
- --equals-json
- --json-subset
- --regex

Examples:
- Exact text:
  - python -m app.cli eval --prompt "ping" --exact-text "OK"
- Equals JSON:
  - Windows (PowerShell): python -m app.cli eval --prompt "..." --equals-json '{ "status": 200 }'
  - macOS/Linux (bash): python -m app.cli eval --prompt '...' --equals-json '{ "status": 200 }'
- JSON subset:
  - python -m app.cli eval --prompt "..." --json-subset '{ "status": 200 }'
- Regex:
  - python -m app.cli eval --prompt "..." --regex "status\\D+200"

Output:
- Prints the model response and an evaluation line like:
  - [EVAL] passed=True reason=

## Benchmarks (CSV)

Run multiple prompts and evaluate them from a CSV file.

- Command:
  - python -m app.cli bench --csv benchmark/benchmark_tests.csv --out bench_out
  - python -m app.cli bench --csv benchmark/benchmark_tests.csv --out "bench_out/my results v1.csv"
- Output:
  - A results file at bench_out/results.csv with columns:
    - id, passed, reason, model, system_prompt_file, eval_mode, question, output_text, profiles_yaml, agent_id, score_* metrics, mcp_call_count, queries

CSV format (columns):
- **id**: identifier
- **question**: user prompt
- **model** (optional): override the default model for this row (ignored if profiles_yaml+agent_id are used)
- **system_prompt_file** (optional): override the default system prompt (legacy path; ignored when using profiles_yaml)
- **profiles_yaml** (optional): path to an agents YAML. If set, the row uses AgentSession loading (tools from catalog, agent backends, prompts from profile).
- **agent_id** (optional): agent id from the profiles YAML (falls back to default_agent if empty)
- **eval_mode**: exact_text | equals_json | json_subset | regex | llm_judge
- **expected**: payload matching eval_mode

#### LLM-as-Judge mode

When `eval_mode` is `llm_judge`, the `expected` column must contain a JSON object with the judge specification:

```json
{
  "gold": {
    "answer_text": "expected answer text",
    "answer_json": {"key": "value"},
    "numeric": 13,
    "reasoning": "expected reasoning steps",
    "queries": ["/ngsi-ld/v1/entities?type=Animal&q=..."]
  },
  "weights": {"correctness": 0.7, "reasoning": 0.2, "efficiency": 0.1},
  "pass_threshold": 0.8,
  "grading_mode": "gated",
  "min_correctness": 1.0,
  "efficiency_budget": 5,
  "notes": "Additional evaluation hints"
}
```

All fields are optional except `gold` (which must be an object). The judge will evaluate correctness, reasoning quality, and query efficiency.

Example CSV (see sample: benchmark/benchmark_tests.csv):
- id,question,model,system_prompt_file,eval_mode,expected
- T1,"Tell me how many animals are located at AgriParcel 005. Answer only with a number",,system3.md,exact_text,"13"
- T2,"List all animals located at AgriParcel 005. Just return the JSON format (Context Broker answer)",gpt-4o,system3.md,json_subset,"[{""id"":""urn:ngsi-ld:Animal:cow003""},{""id"":""urn:ngsi-ld:Animal:cow005""}]"
- T3,"How many animals at AgriParcel 005?",,system3.md,llm_judge,"{""gold"":{""numeric"":13,""queries"":[""/ngsi-ld/v1/entities?type=Animal&q=locatedAt==%22urn:ngsi-ld:AgriParcel:005%22&count=true""]},""weights"":{""correctness"":0.7,""reasoning"":0.2,""efficiency"":0.1},""pass_threshold"":0.8}"

Tips:
- For JSON inside CSV, escape quotes with "".
- If system_prompt_file is empty, the legacy default from `config.yaml` is used (or the built-in default if config.yaml is missing).
- If model is empty, the legacy default from `config.yaml` is used (or the env/built-in default if config.yaml is missing).
- For llm_judge mode, compact the JSON in one line or use a tool to escape it properly.
 - id,question,model,system_prompt_file,eval_mode,expected,profiles_yaml,agent_id
 - T1,"Tell me how many animals are located at AgriParcel 005. Answer only with a number",,system3.md,exact_text,"13",,
 - T2,"List all animals located at AgriParcel 005. Just return the JSON format (Context Broker answer)",gpt-4o,system3.md,json_subset,"[{""id"":""urn:ngsi-ld:Animal:cow003""},{""id"":""urn:ngsi-ld:Animal:cow005""}]",,
 - T3,"List all animals owned by 'Old MacDonald'",,,llm_judge,"{...judge json...}","app/profiles/fiware-agents.yaml","fiware-client"
 
 Tips:
 - For JSON inside CSV, escape quotes with "".
 - If system_prompt_file is empty, the legacy default from `config.yaml` is used (or the built-in default if config.yaml is missing).
 - If model is empty, the legacy default from `config.yaml` is used (or the env/built-in default if config.yaml is missing).
 - If profiles_yaml is provided, tools/backends/prompts come from that YAML; system_prompt_file and model columns are ignored for that row.
 - For llm_judge mode, compact the JSON in one line or use a tool to escape it properly.

### config.yaml selection

All commands accept `--config` (defaults to `config.yaml`):
- `python -m app.cli run --config config.yaml --prompt "..."`

If `config.yaml` is missing, the CLI falls back to env-only mode.

## Prompts

Place system prompts in prompts/ (e.g., system1.md, system2.md, system3.md). Switch with --system-prompt-file as needed.

## Notes

- Ensure the MCP server is reachable and configured with the allowed tools expected by the client.
- Do not commit the .env file or API keys.
- `--out` accepts either a directory (defaulting to results.csv inside it) or a full CSV file path.

## License

This project is licensed under the Apache License 2.0.
