from __future__ import annotations

import abc
from typing import Any, Callable, Dict, List, Optional, Union

from app.tools.specs import ToolSpec

ToolLike = Union[ToolSpec, dict]
TextDeltaHandler = Callable[[str], None]


class ModelBackend(abc.ABC):
	"""Abstract interface for a concrete LLM backend.

	The backend only knows how to talk to the model provider (model id, API key,
	endpoints, and default generation params). Agent-level concerns (system
	prompt, tools list, memory) live in core.Agent.
	"""

	def __init__(
		self,
		*, #any arguments must be passed with keyword (model="gpt-5-mini")
		model_name: str,
		api_key: Optional[str] = None,
		base_url: Optional[str] = None,
		temperature: Optional[float] = None,
		max_output_tokens: Optional[int] = None,
		client_options: Optional[Dict[str, Any]] = None,
	) -> None:
		self.model_name = model_name
		self.api_key = api_key
		self.base_url = base_url
		self.temperature = temperature
		self.max_output_tokens = max_output_tokens
		self.client_options = client_options or {}

	@property
	def model(self) -> str:
		"""Deprecated compatibility accessor for Phase 1 callers."""

		return self.model_name

	@abc.abstractmethod
	def generate(
		self,
		*,
		instructions: str,
		user_prompt: str,
		tools: Optional[List[ToolLike]] = None,
		**kwargs: Any,
	) -> Any:
		"""Execute a generation request against the backend."""

	def stream(
		self,
		*,
		instructions: str,
		user_prompt: str,
		on_text_delta: TextDeltaHandler,
		tools: Optional[List[ToolLike]] = None,
		**kwargs: Any,
	) -> Any:
		"""Execute a streaming generation request against the backend."""

		raise NotImplementedError(f"{type(self).__name__} does not support streaming")

	def _compose_request(
		self,
		*,
		instructions: str,
		user_prompt: str,
		tools: Optional[List[dict]],
		overrides: Optional[Dict[str, Any]] = None,
	) -> Dict[str, Any]:
		payload: Dict[str, Any] = {
			"model": self.model_name,
			"instructions": instructions,
			"input": user_prompt,
		}
		if tools is not None:
			payload["tools"] = tools
		if self.temperature is not None:
			payload["temperature"] = self.temperature
		if self.max_output_tokens is not None:
			payload["max_output_tokens"] = self.max_output_tokens
		if overrides:
			payload.update(overrides)
		return payload
