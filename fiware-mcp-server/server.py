from fastmcp import FastMCP
import os
import time
import signal
import sys
import requests
import json
import logging
import argparse
from urllib.parse import urlparse
from haversine import haversine, Unit

# --- Logging to STDERR only ---
logger = logging.getLogger("cb-assistant")
logger.setLevel(logging.INFO)
logger.handlers.clear()
_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.INFO)
logger.addHandler(_stderr_handler)
logger.propagate = False


# Parse CLI args early so we can configure MCP instance accordingly
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--http", action="store_true", help="Run MCP server over HTTP transport")
_parser.add_argument("--host", default="127.0.0.1", help="HTTP host (only for --http)")
_parser.add_argument("--port", type=int, default=5001, help="HTTP port (only for --http)")
_parser.add_argument("--context-url", default="context-data-loader", choices=["context-data-loader", "mcp-experiments"], help="Select Context Broker JSON-LD context Link header")
_args, _ = _parser.parse_known_args()
_IS_HTTP = _args.http
_HOST = _args.host
_PORT = _args.port
_CONTEXT_URL_FLAG = _args.context_url

_CONTEXT_LINK = '<http://context/user-context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'
if _CONTEXT_URL_FLAG == "mcp-experiments":
    _CONTEXT_LINK = '<http://ld-context/ngsi-context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'

_DEFAULT_CB_HOST = "localhost"
_DEFAULT_CB_PORT = 1026


def _context_env_suffix(context_url: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in context_url).upper()


def _configured_cb_base_url(context_url: str = _CONTEXT_URL_FLAG) -> str:
    context_key = f"FIWARE_CB_BASE_URL_{_context_env_suffix(context_url)}"
    for key in (context_key, "FIWARE_CB_BASE_URL", "CONTEXT_BROKER_URL"):
        value = os.getenv(key)
        if value and value.strip():
            return value.strip().rstrip("/")

    host = os.getenv("FIWARE_CB_HOST")
    port = int(os.getenv("FIWARE_CB_PORT") or _DEFAULT_CB_PORT)
    if host and host.strip():
        host = host.strip()
        if host.startswith(("http://", "https://")):
            return host.rstrip("/")
        return f"http://{host}:{port}"

    return f"http://{_DEFAULT_CB_HOST}:{port}"


_CB_BASE_URL = _configured_cb_base_url()


def _broker_base_url(address: str = _DEFAULT_CB_HOST, port: int = _DEFAULT_CB_PORT) -> str:
    address = str(address or "").strip()
    port = int(port or _DEFAULT_CB_PORT)
    if not address or (address in {_DEFAULT_CB_HOST, "127.0.0.1"} and port == _DEFAULT_CB_PORT):
        return _CB_BASE_URL
    if address.startswith(("http://", "https://")):
        return address.rstrip("/")
    return f"http://{address}:{port}"


def _broker_url(path: str, address: str = _DEFAULT_CB_HOST, port: int = _DEFAULT_CB_PORT) -> str:
    return f"{_broker_base_url(address, port)}/{str(path).lstrip('/')}"


def _query_url_from_params(params: str) -> str:
    raw = str(params or "").strip()
    if raw.upper().startswith("GET "):
        raw = raw[3:].strip()

    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        if parsed.hostname in {_DEFAULT_CB_HOST, "127.0.0.1"} and (
            parsed.port or _DEFAULT_CB_PORT
        ) == _DEFAULT_CB_PORT:
            path = parsed.path.lstrip("/")
            if parsed.query:
                path = f"{path}?{parsed.query}"
            return _broker_url(path)
        return raw

    return _broker_url(raw.lstrip("/").replace(" ", ""))


# Handle SIGINT (Ctrl+C) gracefully
def signal_handler(sig, frame):
    logger.info("Shutting down server gracefully...")  # was print
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# This MCP server provides tools for interacting with a FIWARE Context Broker
mcp = FastMCP(
    name="CB-assistant",
    # stateless_http=_IS_HTTP,  # only enable when running in HTTP mode
)

# This tool gets the Context Broker version
@mcp.tool()
def CB_version(address: str="localhost", port: int=1026) -> str:
    """Return the version of the CB."""
    try:
        url = _broker_url("version", address, port)
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": str(e)})


# This tool gets all entities from the Context Broker
# - You can add extra headers to the request if needed
# - Like adding a personalized context to the request
# - The default headers are "Accept: application/json" and "Content-Type: application/json"
# - This tool returns a JSON object with the entities and a count of the total number of entities in NGSILD-Results-Count
@mcp.tool()
def get_all_entities(address: str="localhost", port: int=1026,  limit=1000, extra_headers: str="") -> str:
    """Get all entities from the Context Broker."""
    try:
        url = _broker_url("ngsi-ld/v1/entities", address, port)
        params = {
            "limit": limit,
            "local": "true",
            "count": "true"
        }
        headers = {
            "Accept": "application/json"
        }

        # Add any extra headers if provided
        if extra_headers:
            try:
                extra_headers_dict = json.loads(extra_headers)
                headers.update(extra_headers_dict)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid extra_headers format. Must be valid JSON string"})

        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": str(e)})



# This tool gets all entity types from the Context Broker
# - You can add extra headers to the request if needed
# - Like adding a personalized context to the request
# - The default headers are "Accept: application/json"
@mcp.tool()
def get_entity_types(address: str="localhost", port: int=1026, limit=1000, extra_headers: str="") -> str:
    """Get entity types from the Context Broker."""
    try:
        url = _broker_url("ngsi-ld/v1/types", address, port)
        params = {
            "limit": limit,
        }
        headers = {
            "Accept": "application/json"
        }

        # Add any extra headers if provided
        if extra_headers:
            try:
                extra_headers_dict = json.loads(extra_headers)
                headers.update(extra_headers_dict)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid extra_headers format. Must be valid JSON string"})

        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": str(e)})


# This tool allows to execute any query to the Context Broker
# - You should provide the full or partial URL of the query
# - For example, to get the entity of type "Building" whose name is "Building 1" you should provide the following URL:
# 'GET http://localhost:1026/ngsi-ld/v1/entities/Building/name/Building%201' or 'GET /ngsi-ld/v1/entities/Building/name/Building%201'
# you need to provide the proper parameter for the GET request
@mcp.tool()
def execute_query(params: str) -> str:
        """
        This tools just passes the query to the Context Broker and returns the response
        You should provide the full or partial VALID query to the Context Broker
        you need to provide the proper parameter for the GET request.
        For example, to get the entity of type "Building" whose name is "Building 1" you should provide the following URL:
        'GET http://localhost:1026/ngsi-ld/v1/entities/Building/name/Building%201' or 'GET /ngsi-ld/v1/entities/Building/name/Building%201'
        """
        full_url = _query_url_from_params(params)

        headers = {
            "Accept": "application/ld+json, application/json;q=0.9, */*;q=0.1",
            "Link": _CONTEXT_LINK,
        }

        try:
            logger.info("Requesting: %s", full_url)
            resp = requests.get(full_url, headers=headers)

            # Try JSON; fall back to text
            try:
                body = resp.json()
            except ValueError:
                body = {"raw_response": resp.text}

            # Return ONLY JSON to stdout
            result = {
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": body,
            }

            # Raise for non-2xx after capturing body, but still return JSON error
            resp.raise_for_status()
            return json.dumps(result)

        except requests.exceptions.RequestException as e:
            # Still return valid JSON
            return json.dumps({"error": str(e), "url": full_url})



# This tool creates or updates entities in the Context Broker
@mcp.tool()
def publish_to_CB(address: str="localhost", port: int=1026, entity_data: dict=None) -> str:  # type: ignore
    """Publish an entity to the CB."""
    broker_url = _broker_url("ngsi-ld/v1/entities", address, port)
    headers = {
        "Content-Type": "application/ld+json"
    }
    try:
        response = requests.post(broker_url, json=entity_data, headers=headers)

        if response.status_code == 201:
            logger.info("Success! Entity created. Status code: %s", response.status_code)
        elif response.status_code == 409:
            logger.info("Entity already exists. Status code: %s", response.status_code)

            # Update the entity if it already exists
            entity_id = entity_data["id"]
            update_url = f"{broker_url}/{entity_id}/attrs"

            # Remove id, type and context for update
            update_data = entity_data.copy()
            update_data.pop("id", None)
            update_data.pop("type", None)
            update_data.pop("@context", None)

            update_response = requests.patch(update_url, json=update_data, headers=headers)
            logger.info("Update attempt result: %s", update_response.status_code)
        else:
            logger.error("Error creating entity. Status code: %s", response.status_code)
            logger.error("Response content: %s", response.text)
    except Exception as e:
        logger.exception("An error occurred: %s", e)

    logger.info("Entity data sent: %s", json.dumps(entity_data, indent=2))
    return json.dumps({"status": "completed"})

# This tool calculates the Haversine distance between two coordinates.
@mcp.tool()
def haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float, unit: str = "km") -> float:
    """
    Calculate the Haversine distance between two geographic points.

    Args:
        lat1: Latitude of the first point.
        lon1: Longitude of the first point.
        lat2: Latitude of the second point.
        lon2: Longitude of the second point.
        unit: Unit of measurement. Options: 'km' (default), 'm', 'mi', 'nmi', 'ft', 'in'.
    """
    unit_mapping = {
        "km": Unit.KILOMETERS,
        "m": Unit.METERS,
        "mi": Unit.MILES,
        "nmi": Unit.NAUTICAL_MILES,
        "ft": Unit.FEET,
        "in": Unit.INCHES
    }
    
    selected_unit = unit_mapping.get(unit.lower(), Unit.KILOMETERS)
    return haversine((lat1, lon1), (lat2, lon2), unit=selected_unit)


if __name__ == "__main__":
    try:
        if _IS_HTTP:
            logger.info(
                "Starting MCP server 'CB-assistant' on %s:%s (HTTP), broker=%s, context=%s",
                _HOST,
                _PORT,
                _CB_BASE_URL,
                _CONTEXT_URL_FLAG,
            )
            mcp.run(
                transport="http",
                host=_HOST,
                port=_PORT,
            )
        else:
            logger.info("Starting MCP server 'CB-assistant' (STDIO)")
            mcp.run(
                transport="stdio",
            )

    except Exception as e:
        logger.exception("Error: %s", e)
        time.sleep(3)
