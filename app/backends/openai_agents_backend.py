from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.backends.model_backend import ModelBackend, TextDeltaHandler, ToolLike
from app.tools.openai_agents_adapter import OpenAIAgentsToolAdapter
from app.tools.specs import ToolSpec


class OpenAIAgentsBackend(ModelBackend):
    """Backend wrapper for the OpenAI Agents SDK."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        client_options: Optional[Dict[str, Any]] = None,
        session_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            client_options=client_options,
        )
        self.agent_options = client_options or {}
        self.session_config = session_config or {}
        self._configure_openai_defaults()

    def generate(
        self,
        *,
        instructions: str,
        user_prompt: str,
        tools: Optional[List[ToolLike]] = None,
        **kwargs: Any,
    ) -> Any:
        if tools:
            if not all(isinstance(tool, ToolSpec) for tool in tools):
                raise ValueError("OpenAI Agents backend requires backend-neutral ToolSpec objects")
        return asyncio.run(
            self._generate_async(
                instructions=instructions,
                user_prompt=user_prompt,
                tools=tools or [],
                **kwargs,
            )
        )

    def stream(
        self,
        *,
        instructions: str,
        user_prompt: str,
        on_text_delta: TextDeltaHandler,
        tools: Optional[List[ToolLike]] = None,
        **kwargs: Any,
    ) -> Any:
        if tools:
            if not all(isinstance(tool, ToolSpec) for tool in tools):
                raise ValueError("OpenAI Agents backend requires backend-neutral ToolSpec objects")
        return asyncio.run(
            self._stream_async(
                instructions=instructions,
                user_prompt=user_prompt,
                on_text_delta=on_text_delta,
                tools=tools or [],
                **kwargs,
            )
        )

    async def _generate_async(
        self,
        *,
        instructions: str,
        user_prompt: str,
        tools: List[ToolLike],
        **kwargs: Any,
    ) -> Any:
        from agents import Runner

        agent_name = str(kwargs.pop("agent_name", None) or "Assistant")
        session_id = kwargs.pop("session_id", None)
        handoff_agents = kwargs.pop("handoff_agents", None) or []
        max_turns = int(kwargs.pop("max_turns", self.agent_options.get("max_turns", 10)))
        max_output_tokens = kwargs.pop("max_output_tokens", None)
        if max_output_tokens is None:
            max_output_tokens = self.max_output_tokens

        session = self._build_session(session_id)

        try:
            async with AsyncExitStack() as stack:
                sdk_agent = await self._build_sdk_agent(
                    instructions=instructions,
                    tools=tools,
                    agent_name=agent_name,
                    max_output_tokens=max_output_tokens,
                    handoff_agents=handoff_agents,
                    stack=stack,
                )
                return await Runner.run(
                    sdk_agent,
                    input=user_prompt,
                    max_turns=max_turns,
                    session=session,
                )
        finally:
            if session is not None:
                close = getattr(session, "close", None)
                if callable(close):
                    close()

    async def _stream_async(
        self,
        *,
        instructions: str,
        user_prompt: str,
        on_text_delta: TextDeltaHandler,
        tools: List[ToolLike],
        **kwargs: Any,
    ) -> Any:
        from agents import Runner
        from openai.types.responses import ResponseTextDeltaEvent

        agent_name = str(kwargs.pop("agent_name", None) or "Assistant")
        session_id = kwargs.pop("session_id", None)
        handoff_agents = kwargs.pop("handoff_agents", None) or []
        max_turns = int(kwargs.pop("max_turns", self.agent_options.get("max_turns", 10)))
        max_output_tokens = kwargs.pop("max_output_tokens", None)
        if max_output_tokens is None:
            max_output_tokens = self.max_output_tokens

        session = self._build_session(session_id)

        try:
            async with AsyncExitStack() as stack:
                sdk_agent = await self._build_sdk_agent(
                    instructions=instructions,
                    tools=tools,
                    agent_name=agent_name,
                    max_output_tokens=max_output_tokens,
                    handoff_agents=handoff_agents,
                    stack=stack,
                )
                result = Runner.run_streamed(
                    sdk_agent,
                    input=user_prompt,
                    max_turns=max_turns,
                    session=session,
                )
                async for event in result.stream_events():
                    if event.type != "raw_response_event":
                        continue
                    if isinstance(event.data, ResponseTextDeltaEvent):
                        delta = getattr(event.data, "delta", "")
                        if delta:
                            on_text_delta(delta)
                return result
        finally:
            if session is not None:
                close = getattr(session, "close", None)
                if callable(close):
                    close()

    async def _build_sdk_agent(
        self,
        *,
        instructions: str,
        tools: List[ToolLike],
        agent_name: str,
        max_output_tokens: Optional[int],
        handoff_agents: List[Any],
        stack: AsyncExitStack,
        seen_agent_names: Optional[set[str]] = None,
    ) -> Any:
        from agents import Agent as SDKAgent

        seen = set(seen_agent_names or set())
        if agent_name in seen:
            raise ValueError(f"Cycle detected in handoff configuration at agent '{agent_name}'")
        seen.add(agent_name)

        runtime = OpenAIAgentsToolAdapter.to_runtime(tools)
        model_settings = self._build_model_settings(max_output_tokens=max_output_tokens)
        mcp_servers = [await stack.enter_async_context(server) for server in runtime.mcp_servers]
        sdk_handoffs = []
        for handoff_agent in handoff_agents:
            target_backend = getattr(handoff_agent, "model_backend", None)
            if not isinstance(target_backend, OpenAIAgentsBackend):
                raise ValueError(
                    "OpenAI Agents handoff targets must also use the openai_agents backend "
                    f"(target={getattr(handoff_agent, 'name', '<unknown>')!r})"
                )
            sdk_handoffs.append(
                await target_backend._build_sdk_agent(
                    instructions=handoff_agent.system_prompt,
                    tools=handoff_agent.tools,
                    agent_name=handoff_agent.name,
                    max_output_tokens=target_backend.max_output_tokens,
                    handoff_agents=getattr(handoff_agent, "delegates", []),
                    stack=stack,
                    seen_agent_names=seen,
                )
            )

        return SDKAgent(
            name=agent_name,
            instructions=instructions,
            model=self.model_name,
            model_settings=model_settings,
            tools=runtime.tools,
            mcp_servers=mcp_servers,
            handoffs=sdk_handoffs,
        )

    def _build_model_settings(self, *, max_output_tokens: Optional[int]) -> Any:
        from agents import ModelSettings

        settings: Dict[str, Any] = {}
        if self.temperature is not None:
            settings["temperature"] = self.temperature
        if max_output_tokens is not None:
            settings["max_tokens"] = max_output_tokens

        extra_settings = self.agent_options.get("model_settings")
        if isinstance(extra_settings, dict):
            settings.update(extra_settings)
        settings.setdefault("include_usage", True)
        return ModelSettings(**settings)

    def _build_session(self, session_id: Optional[str]) -> Any:
        if not session_id:
            return None

        cfg = self.session_config
        if cfg and cfg.get("enabled") is False:
            return None

        provider = str(cfg.get("provider") or cfg.get("type") or "sqlite").lower()
        if provider != "sqlite":
            raise ValueError(f"OpenAI Agents backend only supports sqlite sessions, got {provider!r}")

        db_path = cfg.get("path") or cfg.get("db_path") or "data/sessions.sqlite"
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        from agents import SQLiteSession

        return SQLiteSession(str(session_id), db_path=db_path)

    def _configure_openai_defaults(self) -> None:
        from agents import AsyncOpenAI
        from agents import set_default_openai_api, set_default_openai_client, set_default_openai_key

        if not self.api_key:
            raise ValueError("OpenAIAgentsBackend requires an api_key")

        set_default_openai_api("responses")
        if self.base_url or self.client_options:
            opts = dict(self.client_options)
            opts.pop("max_turns", None)
            opts.pop("model_settings", None)
            opts.pop("session", None)
            if self.base_url:
                opts.setdefault("base_url", self.base_url)
            client = AsyncOpenAI(api_key=self.api_key, **opts)
            set_default_openai_client(client)
        else:
            set_default_openai_key(self.api_key)
