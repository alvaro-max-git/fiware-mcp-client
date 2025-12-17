from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.backends.backend_factory import create_backend
from app.core.agent import Agent
from app.core.config import (
	ProfilesConfig,
	load_mcp_servers_from_env,
	load_profiles_config,
	load_tools_config,
)
from app.core.tool_factory import ToolFactory
from app.prompts import load_prompt


def _load_tool_factory_if_available(tools_yaml: Optional[Path]) -> Optional[ToolFactory]:
	candidates: List[Path] = []
	if tools_yaml is not None:
		candidates.append(Path(tools_yaml))
	else:
		candidates.append(Path("app/tools/tools.yaml"))

	for candidate in candidates:
		if candidate.exists():
			catalog = load_tools_config(candidate)
			return ToolFactory(catalog)
	return None


def _resolve_tools(tool_names: List[str], tool_factory: Optional[ToolFactory]) -> List[dict]:
	if tool_names:
		if tool_factory:
			return tool_factory.build_tools(tool_names)

		# Backward compatibility: fallback to environment-defined MCP servers.
		available = load_mcp_servers_from_env()
		tools: List[dict] = []
		for name in tool_names:
			srv = available.get(name)
			if not srv:
				raise ValueError(
					f"Tool '{name}' not found in catalog and no MCP env config present"
				)
			tools.append(srv.to_openai_tool())
		return tools

	return []


def _load_profiles(yaml_path: Path) -> ProfilesConfig:
	return load_profiles_config(yaml_path)


def _compose_system_prompt(system_prompt: str, *, read_only: bool = True) -> str:
	if read_only:
		return f"{system_prompt}\n\nRead only mode={read_only}. If something fails, explain why."
	return system_prompt


def load_agent(
	profile_id: str,
	yaml_path: str,
	*,
	prompts_dir: Path = Path("prompts"),
	read_only: bool = True,
	tools_yaml: Optional[Path] = None,
) -> Agent:
	cfg = _load_profiles(Path(yaml_path))
	profile = cfg.get_agent(profile_id)
	tool_factory = _load_tool_factory_if_available(tools_yaml)

	backend = create_backend(profile.backend)
	tools = _resolve_tools(profile.tools, tool_factory)
	system_prompt = _compose_system_prompt(
		load_prompt(prompts_dir, profile.system_prompt), read_only=read_only
	)

	return Agent(
		name=profile.id,
		system_prompt=system_prompt,
		model_backend=backend,
		tools=tools,
	)


@dataclass
class AgentSession:
	"""Holds a set of agents and routes prompts to the selected one."""

	agents: Dict[str, Agent] = field(default_factory=dict)
	default_agent: Optional[str] = None

	def get_agent(self, agent_id: Optional[str] = None) -> Agent:
		selected = agent_id or self.default_agent
		if selected and selected in self.agents:
			return self.agents[selected]
		if self.agents:
			return next(iter(self.agents.values()))
		raise ValueError("No agents registered in this session")

	def ask(self, prompt: str, *, agent_id: Optional[str] = None, **kwargs):
		agent = self.get_agent(agent_id)
		return agent.generate(prompt, **kwargs)

	@classmethod
	def from_yaml(
		cls,
		*,
		yaml_path: Path,
		default_agent: Optional[str] = None,
		prompts_dir: Path = Path("prompts"),
		read_only: bool = True,
		tools_yaml: Optional[Path] = None,
	) -> "AgentSession":
		profiles = _load_profiles(yaml_path)
		tool_factory = _load_tool_factory_if_available(tools_yaml)
		session = cls(default_agent=default_agent or profiles.default_agent)

		for profile in profiles.agents:
			backend = create_backend(profile.backend)
			tools = _resolve_tools(profile.tools, tool_factory)
			system_prompt = _compose_system_prompt(
				load_prompt(prompts_dir, profile.system_prompt), read_only=read_only
			)
			session.agents[profile.id] = Agent(
				name=profile.id,
				system_prompt=system_prompt,
				model_backend=backend,
				tools=tools,
			)

		return session
