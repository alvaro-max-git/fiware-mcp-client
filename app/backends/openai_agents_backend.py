from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.backends.model_backend import ModelBackend


class OpenAIAgentsBackend(ModelBackend):
    """Placeholder backend for the OpenAI Agents SDK."""

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
        self.agent_options = client_options or {}

    def generate(
        self,
        *,
        instructions: str,
        user_prompt: str,
        tools: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError("OpenAI Agents backend will be implemented in phase two")
