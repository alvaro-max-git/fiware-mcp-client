from pathlib import Path

import pytest

from app.core.config import load_tools_config
from app.core.tool_factory import ToolFactory


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
    tools = factory.build_tools(["fiware-mcp"])

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
    tools = factory.build_tools(["code-interpreter"])

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
    tools = factory.build_tools(
        ["code-interpreter"],
        overrides={
            "code-interpreter": {"container": {"memory_limit": "8g"}}
        },
    )

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
