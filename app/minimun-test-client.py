import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    # This is the default and can be omitted
    api_key=os.environ.get("OPENAI_API_KEY"),
)
MCP_URL = os.getenv("MCP_URL")

tools = [
    {
        "type": "mcp",
        "server_label": "fiware-mcp",
        "server_url": MCP_URL,
        # limitar herramientas que verá el modelo
        "allowed_tools": ["CB_version", "get_all_entities", "get_entity_types"],
        # ejecuta sin pedir confirmación
        "require_approval": "never",
    }
]

prompt = (
    "Use the tools to retrieve all entities with limit=5 and summarize how many entities you retrieved and their types."
)

response = client.responses.create(
    model="gpt-4o-mini",
    tools=tools, # type: ignore
    instructions="You are a client that answers questions from the user and queries a context broker via MCP to retrieve answers",
    input=prompt,
    max_output_tokens=800,
)

print(response.output_text)