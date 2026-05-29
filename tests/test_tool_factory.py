from pathlib import Path

import pytest

from app.core.config import load_tools_config
from app.core.tool_factory import ToolFactory
from app.tools.openai_agents_adapter import OpenAIAgentsToolAdapter
from app.tools.openai_responses_adapter import OpenAIResponsesToolAdapter
from app.tools.specs import MCP_HOSTED, MCP_STREAMABLE_HTTP, OPENAI_HOSTED_TOOL, ToolSpec


def test_tool_factory_builds_mcp_tool(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: fiware-mcp
            type: mcp
            config:
              label: fiware-mcp
              url: https://example.com/mcp
              allowed_tools: execute_query, get_entity_types
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    specs = factory.build_tools(["fiware-mcp"])
    tools = OpenAIResponsesToolAdapter.to_tool_dicts(specs)

    assert specs and specs[0].type == MCP_HOSTED
    assert specs[0].config["server_label"] == "fiware-mcp"
    assert specs[0].config["server_url"] == "https://example.com/mcp"
    assert tools and tools[0]["type"] == "mcp"
    assert tools[0]["server_label"] == "fiware-mcp"
    assert tools[0]["server_url"] == "https://example.com/mcp"
    assert tools[0]["allowed_tools"] == ["execute_query", "get_entity_types"]


def test_tool_factory_missing_url_raises(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: fiware-mcp
            type: mcp
            config:
              label: fiware-mcp
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    with pytest.raises(ValueError):
        factory.build_tools(["fiware-mcp"])


def test_tool_factory_builds_openai_responses_tool(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: code-interpreter
            type: openai-responses-tool
            config:
              type: code_interpreter
              container:
                type: auto
                memory_limit: 4g
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    specs = factory.build_tools(["code-interpreter"])
    tools = OpenAIResponsesToolAdapter.to_tool_dicts(specs)

    assert specs and specs[0].type == OPENAI_HOSTED_TOOL
    assert tools and tools[0]["type"] == "code_interpreter"
    assert tools[0]["container"]["memory_limit"] == "4g"


def test_tool_factory_applies_overrides(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: code-interpreter
            type: openai-responses-tool
            config:
              type: code_interpreter
              container:
                type: auto
                memory_limit: 4g
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    specs = factory.build_tools(
        ["code-interpreter"],
        overrides={
            "code-interpreter": {"container": {"memory_limit": "8g"}}
        },
    )
    tools = OpenAIResponsesToolAdapter.to_tool_dicts(specs)

    assert tools and tools[0]["container"]["memory_limit"] == "8g"


def test_tool_factory_missing_type_for_openai_tool_raises(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: code-interpreter
            type: openai-responses-tool
            config:
              container:
                type: auto
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    with pytest.raises(ValueError):
        factory.build_tools(["code-interpreter"])


def test_tool_factory_builds_streamable_http_spec(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: fiware-local
            type: mcp_streamable_http
            config:
              name: fiware-mcp
              url: http://127.0.0.1:5001/mcp
              allowed_tools:
                - execute_query
              cache_tools_list: true
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    specs = factory.build_tools(["fiware-local"])

    assert specs[0].type == MCP_STREAMABLE_HTTP
    assert specs[0].config["allowed_tools"] == ["execute_query"]
    with pytest.raises(ValueError, match="Responses backend"):
        OpenAIResponsesToolAdapter.to_tool_dicts(specs)


def test_agents_adapter_builds_hosted_mcp_tool(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: fiware-hosted
            type: mcp_hosted
            config:
              server_label: fiware-mcp
              server_url: https://example.com/mcp
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    runtime = OpenAIAgentsToolAdapter.to_runtime(factory.build_tools(["fiware-hosted"]))

    assert len(runtime.tools) == 1
    assert runtime.mcp_servers == []


def test_agents_adapter_builds_local_mcp_server(tmp_path: Path):
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
        tools_definitions:
          - name: fiware-local
            type: mcp_streamable_http
            config:
              name: fiware-mcp
              url: http://127.0.0.1:5001/mcp
              allowed_tools: execute_query
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_tools_config(tools_yaml)
    factory = ToolFactory(catalog)
    runtime = OpenAIAgentsToolAdapter.to_runtime(factory.build_tools(["fiware-local"]))

    assert runtime.tools == []
    assert len(runtime.mcp_servers) == 1


def test_agents_adapter_builds_code_interpreter_tool():
    runtime = OpenAIAgentsToolAdapter.to_runtime(
        [
            ToolSpec(
                name="code-interpreter",
                type=OPENAI_HOSTED_TOOL,
                config={
                    "provider": "responses",
                    "type": "code_interpreter",
                    "container": {"type": "auto", "memory_limit": "4g"},
                },
            )
        ]
    )

    assert len(runtime.tools) == 1
    assert runtime.tools[0].name == "code_interpreter"
    assert runtime.tools[0].tool_config["container"]["memory_limit"] == "4g"
