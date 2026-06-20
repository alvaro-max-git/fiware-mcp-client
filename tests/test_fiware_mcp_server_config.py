from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest


SERVER_PATH = Path(__file__).resolve().parents[1] / "fiware-mcp-server" / "server.py"


def _load_server(monkeypatch: pytest.MonkeyPatch, *args: str):
    module_name = f"fiware_mcp_server_under_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(sys, "argv", ["server.py", *args])
    spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_mcp_server_uses_global_broker_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FIWARE_CB_BASE_URL", "http://broker:1026")
    monkeypatch.delenv("FIWARE_CB_BASE_URL_CONTEXT_DATA_LOADER", raising=False)
    monkeypatch.delenv("FIWARE_CB_BASE_URL_MCP_EXPERIMENTS", raising=False)

    server = _load_server(monkeypatch)

    assert server._broker_url("version") == "http://broker:1026/version"
    assert (
        server._query_url_from_params("GET http://localhost:1026/ngsi-ld/v1/types?limit=5")
        == "http://broker:1026/ngsi-ld/v1/types?limit=5"
    )


def test_mcp_server_prefers_context_specific_broker_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FIWARE_CB_BASE_URL", "http://fallback:1026")
    monkeypatch.setenv("FIWARE_CB_BASE_URL_MCP_EXPERIMENTS", "http://experiments:1027")
    monkeypatch.delenv("FIWARE_CB_BASE_URL_CONTEXT_DATA_LOADER", raising=False)

    server = _load_server(monkeypatch, "--context-url", "mcp-experiments")

    assert server._CB_BASE_URL == "http://experiments:1027"
    assert server._broker_url("/ngsi-ld/v1/entities") == "http://experiments:1027/ngsi-ld/v1/entities"


def test_mcp_server_is_read_only_by_default(monkeypatch: pytest.MonkeyPatch):
    server = _load_server(monkeypatch)

    tools = asyncio.run(server.mcp.get_tools())
    disabled_response = json.loads(server.publish_to_CB(entity_data={"id": "urn:test"}))

    assert server._WRITE_MODE is False
    assert "publish_to_CB" not in tools
    assert disabled_response["error"] == "write_mode_disabled"


def test_mcp_server_write_mode_registers_publish_tool(monkeypatch: pytest.MonkeyPatch):
    server = _load_server(monkeypatch, "--write-mode")

    tools = asyncio.run(server.mcp.get_tools())

    assert server._WRITE_MODE is True
    assert "publish_to_CB" in tools
