# fiware-mcp-client

Client that queries a FIWARE NGSI-LD Context Broker via an MCP server using an OpenAI model. It supports single runs and response evaluation.

- CLI: app/cli.py
- Config: app/config.py
- Runner: app/runner.py
- Evaluator: app/evaluator.py
- Types: app/types.py
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

Do not commit secrets. Use .template.env as a starting point:
- Copy: cp .template.env .env (macOS/Linux) or copy .template.env .env (Windows)

Key variables (loaded by AppConfig.from_env):
- OPENAI_API_KEY: OpenAI API key.
- OPENAI_MODEL: e.g., gpt-5-nano.
- MAX_OUTPUT_TOKENS: Max output tokens.
- MCP_LABEL: Display name for the MCP toolset (e.g., fiware-mcp).
- MCP_URL: MCP server endpoint (must end with /mcp).
- MCP_ALLOWED_TOOLS: Comma-separated tools to expose (e.g., execute_query,get_entity_types,CB_version).
- PROMPTS_DIR: Prompts directory (e.g., prompts).
- SYSTEM_PROMPT_FILE: Default system prompt file (e.g., system3.md).
- LOG_LEVEL, LOG_TO_FILE, LOGS_DIR: Logging configuration.
- READ_ONLY: true/false.
- ENABLE_CODE_INTERPRETER: true/false to expose OpenAI's python sandbox (default: true).
- CODE_INTERPRETER_MEMORY_LIMIT: Memory quota for the sandbox (default: 4g).

Multiple MCP servers (optional):
- Use MCP_0_, MCP_1_, etc. prefixes (LABEL, URL, ALLOWED_TOOLS) to register several toolsets.

## Usage

Run the CLI:
- python -m app.cli <command> [options]

System prompt selection:
- Defaults to SYSTEM_PROMPT_FILE in .env.
- Override per run with --system-prompt-file.

### Single run

- Example:
  - Windows (PowerShell):
    - python -m app.cli run --prompt "List available entity types" --system-prompt-file prompts/system3.md
  - macOS/Linux (bash):
    - python -m app.cli run --prompt 'List available entity types' --system-prompt-file prompts/system3.md

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
    - id, passed, reason, model, system_prompt_file, eval_mode, prompt, output_text

CSV format:
- Columns: id, question, model, system_prompt_file, eval_mode, expected
- **model** (optional): Override the default model for this specific test (e.g., `gpt-4o`, `gpt-4o-mini`)
- **system_prompt_file** (optional): Override the default system prompt for this test
- eval_mode values:
  - exact_text | equals_json | json_subset | regex | llm_judge
- expected:
  - Plain text for exact_text
  - JSON for equals_json/json_subset
  - Regex pattern for regex

Code Interpreter:
- Controlled by env var `ENABLE_CODE_INTERPRETER` (`true` by default if unset).
- To disable: `ENABLE_CODE_INTERPRETER=false`.
- When enabled, `AppConfig.build_tools()` adds:
  - `{"type": "code_interpreter", "container": {"type": "auto", "memory_limit": "4g"}}`
  which is then passed to `OpenAI.responses.create(...)` for all runs.

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
- If system_prompt_file is empty, the default from .env is used.
- If model is empty, the default OPENAI_MODEL from .env is used.
- For llm_judge mode, compact the JSON in one line or use a tool to escape it properly.

## Prompts

Place system prompts in prompts/ (e.g., system1.md, system2.md, system2.4.md, system3.md, system3.4.md). Prompts 2.4/3.4 expect the Code Interpreter tool to be enabled (default) so they can offload JSON post-processing when needed.

## Notes

- Ensure the MCP server is reachable and configured with the allowed tools expected by the client.
- Do not commit the .env file or API keys.
- `--out` accepts either a directory (defaulting to results.csv inside it) or a full CSV file path.
- To trace whether the Code Interpreter tool was enabled or executed, set `LOG_LEVEL=DEBUG`; the runner will log the prepared tool payload and any Code Interpreter invocations in `logs/run.log`.
