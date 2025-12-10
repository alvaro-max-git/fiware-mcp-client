from __future__ import annotations

import os
from typing import Any, Dict, Optional, Protocol

from app.backends.model_backend import ModelBackend
from app.backends.openai_agents_backend import OpenAIAgentsBackend
from app.backends.openai_responses_backend import OpenAIResponsesBackend


class BackendConfig(Protocol):
	"""Minimal shape required to build a backend."""

	type: str
	model: str
	temperature: Optional[float]
	max_output_tokens: Optional[int]
	base_url: Optional[str]
	client_options: Optional[Dict[str, Any]]
	api_key: Optional[str]


def _resolve_api_key(config: BackendConfig, explicit_key: Optional[str]) -> str:
	key = explicit_key or getattr(config, "api_key", None) or os.getenv("OPENAI_API_KEY")
	if not key:
		raise ValueError("OPENAI_API_KEY is required to initialize a backend")
	return key


def create_backend(config: BackendConfig, *, api_key: Optional[str] = None) -> ModelBackend:
	backend_type = str(getattr(config, "type", "")).lower()
	if not backend_type:
		raise ValueError("Backend type must be provided")

	model = getattr(config, "model", None)
	if not model:
		raise ValueError("Backend model must be provided")

	resolved_api_key = _resolve_api_key(config, api_key)
	common_kwargs = {
		"model": model,
		"api_key": resolved_api_key,
		"temperature": getattr(config, "temperature", None),
		"max_output_tokens": getattr(config, "max_output_tokens", None),
		"base_url": getattr(config, "base_url", None),
		"client_options": getattr(config, "client_options", None),
	}

	if backend_type in {"openai_responses", "openai"}:
		return OpenAIResponsesBackend(**common_kwargs)
	if backend_type in {"openai_agent", "openai_agents"}:
		return OpenAIAgentsBackend(**common_kwargs)

	raise ValueError(f"Unknown backend type: {backend_type}")
