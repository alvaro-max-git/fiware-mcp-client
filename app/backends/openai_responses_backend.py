from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.backends.model_backend import ModelBackend


class OpenAIResponsesBackend(ModelBackend):
	"""Backend wrapper for OpenAI Responses API."""

	def __init__(
		self,
		*,
		model: str,
		api_key: str,
		base_url: Optional[str] = None,
		temperature: Optional[float] = None,
		max_output_tokens: Optional[int] = None,
		client_options: Optional[Dict[str, Any]] = None,
	) -> None:
		super().__init__(
			model=model,
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
		tools: Optional[List[dict]] = None,
		**kwargs: Any,
	) -> Any:
		payload = self._compose_request(
			instructions=instructions,
			user_prompt=user_prompt,
			tools=tools,
			overrides=kwargs,
		)
		return self._client.responses.create(**payload)
