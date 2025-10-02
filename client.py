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
        # MUY RECOMENDADO: limitar herramientas que verá el modelo
        "allowed_tools": ["CB_version", "get_all_entities", "get_entity_types"],
        # para pruebas, ejecuta sin pedir confirmación humana
        "require_approval": "never",
    }
]

prompt = (
    "Use CB version tool and tell me the Context Broker version."
)

response = client.responses.create(
    model="gpt-4o-mini",
    tools=tools,
    instructions="You are a client that queries a Context Broker through a MCP Server, answering users' questions.",
    input=prompt,
    max_output_tokens=800,
)

print(response.output_text)