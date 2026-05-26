from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.backends.model_backend import ModelBackend, ToolLike
from app.tools.openai_responses_adapter import OpenAIResponsesToolAdapter


class OpenAIResponsesBackend(ModelBackend):
	"""Backend wrapper for OpenAI Responses API."""

	def __init__(
		self,
		*,
		model_name: str,
		api_key: str,
		base_url: Optional[str] = None,
		temperature: Optional[float] = None,
		max_output_tokens: Optional[int] = None,
		client_options: Optional[Dict[str, Any]] = None,
	) -> None:
		super().__init__(
			model_name=model_name,
			api_key=api_key,
			base_url=base_url,
			temperature=temperature,
			max_output_tokens=max_output_tokens,
			client_options=client_options,
		)
		if not self.api_key:
			raise ValueError("OpenAIResponsesBackend requires an api_key")

		opts = dict(self.client_options)
		if self.base_url:
			opts.setdefault("base_url", self.base_url)
		self._client = OpenAI(api_key=self.api_key, **opts)

	def generate(
		self,
		*,
		instructions: str,
		user_prompt: str,
		tools: Optional[List[ToolLike]] = None,
		**kwargs: Any,
	) -> Any:
		kwargs.pop("agent_name", None)
		kwargs.pop("session_id", None)
		kwargs.pop("max_turns", None)
		kwargs.pop("handoff_agents", None)
		tool_payload = (
			OpenAIResponsesToolAdapter.to_tool_dicts(tools)
			if tools is not None
			else None
		)
		payload = self._compose_request(
			instructions=instructions,
			user_prompt=user_prompt,
			tools=tool_payload,
			overrides=kwargs,
		)
		return self._client.responses.create(**payload)
