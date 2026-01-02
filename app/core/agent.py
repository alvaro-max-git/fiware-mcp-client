from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from app.backends.model_backend import ModelBackend


@dataclass
class Agent:
	"""Lightweight agent wrapper that couples a system prompt with a backend."""

	name: str
	system_prompt: str
	model_backend: ModelBackend
	tools: List[dict] = field(default_factory=list)
	delegates: List["Agent"] = field(default_factory=list)

	def generate(
		self,
		user_prompt: str,
		*,
		tools: Optional[List[dict]] = None,
		**kwargs: Any,
	) -> Any:
		"""Run a turn against the underlying backend."""

		active_tools = tools if tools is not None else self.tools
		return self.model_backend.generate(
			instructions=self.system_prompt,
			user_prompt=user_prompt,
			tools=active_tools,
			**kwargs,
		)
