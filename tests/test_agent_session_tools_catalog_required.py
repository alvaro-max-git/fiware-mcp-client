from pathlib import Path
import textwrap

import pytest

from app.core.agent_session import AgentSession


def test_yaml_mode_requires_tools_catalog(tmp_path: Path):
    profiles_yaml = tmp_path / "agents.yaml"
    profiles_yaml.write_text(
        textwrap.dedent(
            """
            default_agent: a
            agents:
              - id: a
                system_prompt: system.md
                backend:
                  type: openai_responses
                  model: gpt-5
                tools: [fiware-mcp]
            """
        ).strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no tools catalog"):
        AgentSession.from_yaml(yaml_path=profiles_yaml, tools_yaml=tmp_path / "missing-tools.yaml")
