"""Offline tests: the tools against a local stand-in for the API on 127.0.0.1, by their own run, by each tool as an
AgentSession calls it (LiveKit's own prepare_function_arguments, then the tool), in a ToolContext, a Toolset and an
Agent, and as LiveKit turns them into each provider's tools."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

import pytest
from livekit.agents import Agent, llm
from livekit.agents.llm import ToolError
from livekit.agents.llm.utils import prepare_function_arguments

from livekit_agents_datacircle import (
    TOOL_NAMES,
    DatacircleError,
    DatacircleToolset,
    datacircle_tool,
    datacircle_tools,
    run,
)
from livekit_agents_datacircle import _api

PLAN = {"api": "Employee email", "rank": 1, "provider": "Hunter", "plan": "Starter", "score": 80.1, "perThousand": 4.9,
        "page": "https://datacircle.dev/x", "terms": "long", "aggregators": ["a"]}
SEEN = []
BUSY = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        SEEN.append((url.path, query, self.headers.get("User-Agent")))
        headers = {}
        if url.path == "/v1/plans" and query.get("query") == "busy" and not BUSY:
            BUSY.append(1)
            status, body, headers = 429, {"error": "slow down"}, {"Retry-After": "1"}
        elif url.path == "/v1/apis":
            status, body = 200, [{"api": "Employee email", "slug": "email-finder", "plans": 9, "providers": 3, "extra": 1},
                                 {"api": "Employee profile", "slug": "linkedin-profile", "plans": 4, "providers": 2}]
        elif url.path == "/v1/apis/email-finder/best":
            status, body = 200, {"api": "Employee email", "slug": "email-finder", "total": 1, "plans": [PLAN]}
        elif url.path.startswith("/v1/apis/"):
            status, body = 404, {"error": "no API has the slug nope", "slugs": ["email-finder", "linkedin-profile"]}
        elif url.path == "/v1/plans" and query.get("query") == "down":
            status, body = 503, {"error": "down for a minute"}
        elif url.path == "/v1/plans":
            status, body = 200, {"total": 1, "offset": 0, "plans": [PLAN]}
        elif url.path == "/v1/providers/bright-data":
            status, body = 200, {"provider": "Bright Data", "slug": "bright-data", "website": "https://brightdata.com",
                                 "apis": [{"api": "Employee email", "slug": "email-finder", "rank": 7, "sheetPage": "s",
                                           "plans": [dict(PLAN, rank=9, plan="B"), dict(PLAN, rank=7, plan="A")]}]}
        else:
            status, body = 404, {"error": "no provider has this slug"}
        data = json.dumps(body).encode()
        self.send_response(status)
        for key, value in {"Content-Type": "application/json", "Content-Length": str(len(data)), **headers}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module", autouse=True)
def stand_in():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    before = _api.BASE_URL
    _api.BASE_URL = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield
    _api.BASE_URL = before
    server.shutdown()


def info(tool: Any) -> Any:
    """A raw function tool's info: LiveKit before 1.4 keeps it on the function itself."""
    return getattr(tool, "info", None) or getattr(tool, "__livekit_raw_tool_info")


def called(name: str, **arguments: Any) -> Any:
    """A tool's result as an AgentSession gets it: LiveKit's own parse of the model's JSON arguments, then the call."""
    tool = llm.ToolContext(datacircle_tools()).function_tools[name]
    args, kwargs = prepare_function_arguments(fnc=tool, json_arguments=json.dumps(arguments))
    return json.loads(asyncio.run(tool(*args, **kwargs)))


def refused(name: str, **arguments: Any) -> str:
    with pytest.raises(ToolError) as raised:
        called(name, **arguments)
    return raised.value.message


def test_the_schemas():
    tools = datacircle_tools()
    assert [info(tool).name for tool in tools] == TOOL_NAMES and all(llm.is_raw_function_tool(tool) for tool in tools)
    for tool in tools:
        schema = info(tool).raw_schema
        assert "https://datacircle.dev" in schema["description"] and schema["parameters"]["type"] == "object"
    assert info(datacircle_tool("datacircle_best_plans")).raw_schema["parameters"]["required"] == ["slug"]
    assert info(datacircle_tool("datacircle_provider")).raw_schema["parameters"]["required"] == ["slug"]
    assert info(datacircle_tool("datacircle_list_apis")).raw_schema["parameters"]["required"] == []
    search = info(datacircle_tool("datacircle_search_plans")).raw_schema["parameters"]["properties"]
    assert search["sort"]["enum"] == ["score", "provider", "price"]
    assert search["limit"] == {"type": "integer", "minimum": 1, "maximum": 50,
                               "description": "How many plans to give, 1 to 50. 10 when left out."}
    search["limit"]["maximum"] = 5  # each tool holds its own copy
    assert info(datacircle_tool("datacircle_search_plans")).raw_schema["parameters"]["properties"]["limit"]["maximum"] == 50
    assert [info(tool).name for tool in datacircle_tools(["datacircle_provider", "datacircle_list_apis"])] == \
        ["datacircle_provider", "datacircle_list_apis"]
    assert datacircle_tools([]) == []
    assert datacircle_tools()[0] is not datacircle_tools()[0]  # a new tool each time, never one shared function
    with pytest.raises(ValueError, match="its tools are datacircle_list_apis"):
        datacircle_tools(["datacircle_nope"])
    with pytest.raises(TypeError):
        datacircle_tools("datacircle_provider")


def test_each_tool_as_a_session_calls_it():
    SEEN.clear()
    assert called("datacircle_list_apis", query="profile") == \
        {"total": 1, "apis": [{"api": "Employee profile", "slug": "linkedin-profile", "plans": 4, "providers": 2}]}
    assert called("datacircle_list_apis", limit=1)["apis"][0]["slug"] == "email-finder"
    best = called("datacircle_best_plans", slug="Email Finder", limit=3)
    assert best["plans"] == [{key: value for key, value in PLAN.items() if key not in ("terms", "aggregators")}]
    found = called("datacircle_search_plans", query="hunter", sort="price", limit=2)
    assert found["total"] == 1 and "terms" not in found["plans"][0]
    seller = called("datacircle_provider", slug="Bright Data")
    assert seller["apis"] == [{"api": "Employee email", "slug": "email-finder", "rank": 7, "plans": 2,
                               "best": {"plan": "A", "score": 80.1, "perThousand": 4.9, "page": "https://datacircle.dev/x"}}]
    assert ("/v1/apis/email-finder/best", {"limit": "3"}, _api.USER_AGENT) in SEEN
    assert ("/v1/plans", {"query": "hunter", "sort": "price", "limit": "2"}, _api.USER_AGENT) in SEEN
    assert _api.USER_AGENT.startswith("livekit-agents-datacircle/")
    assert called("datacircle_best_plans", slug="email-finder", color="red")["total"] == 1  # an argument it doesn't take
    assert called("datacircle_list_apis") == run("datacircle_list_apis")


def test_refusals_reach_the_model_in_the_apis_words():
    words = refused("datacircle_best_plans", slug="nope")
    assert "answered 404" in words and "email-finder, linkedin-profile" in words
    assert "no provider has this slug" in refused("datacircle_provider", slug="nobody")
    assert "answered 503" in refused("datacircle_search_plans", query="down")
    assert "Give a provider's slug" in refused("datacircle_provider", slug="  ")
    assert "Give an API's slug" in refused("datacircle_best_plans")
    assert "answered 404" in run("datacircle_best_plans", {"slug": "nope"})["error"]
    with pytest.raises(DatacircleError) as raised:
        _api.get("/plans", {"query": "down"})
    assert raised.value.status == 503 and raised.value.retryable


def test_arguments_out_of_range_never_reach_the_api():
    SEEN.clear()
    assert refused("datacircle_search_plans", sort="cheapest") == "sort must be score, provider or price, not 'cheapest'"
    assert refused("datacircle_best_plans", slug="email-finder", limit=80) == "limit must be from 1 to 50, not 80"
    assert "offset must be a whole number" in run("datacircle_search_plans", {"offset": 1.5})["error"]
    assert SEEN == []
    assert called("datacircle_best_plans", slug="email-finder", limit="2")["total"] == 1  # a number sent as text
    assert run("datacircle_list_apis", None)["total"] == 2
    with pytest.raises(ValueError):
        run("datacircle_nope", {})


def test_waits_once_on_429():
    BUSY.clear()
    assert called("datacircle_search_plans", query="busy")["total"] == 1


def test_an_agent_takes_them_beside_its_own():
    @llm.function_tool
    async def lookup_weather(location: str) -> str:
        """Looks up the weather."""
        return "sunny"

    agent = Agent(instructions="Find GTM APIs.", tools=[lookup_weather, *datacircle_tools()])
    names = list(llm.ToolContext(agent.tools).function_tools)
    assert sorted(names) == sorted(["lookup_weather", *TOOL_NAMES])


def test_a_toolset():
    if not hasattr(llm, "Toolset"):
        with pytest.raises(ImportError, match="livekit-agents 1.4 or later"):
            DatacircleToolset()
        return
    toolset = DatacircleToolset()
    assert isinstance(toolset, llm.Toolset) and toolset.id == "datacircle"
    assert [info(tool).name for tool in toolset.tools] == TOOL_NAMES
    some = DatacircleToolset(["datacircle_best_plans"])
    context = llm.ToolContext([some])
    assert list(context.function_tools) == ["datacircle_best_plans"] and context.toolsets == [some]
    agent = Agent(instructions="Find GTM APIs.", tools=[DatacircleToolset()])
    assert sorted(llm.ToolContext(agent.tools).function_tools) == sorted(TOOL_NAMES)


@pytest.mark.parametrize("format", ["openai", "openai.responses", "google", "anthropic", "aws"])
def test_each_providers_tools(format):
    context = llm.ToolContext(datacircle_tools())
    if not hasattr(context, "parse_function_tools"):
        pytest.skip("LiveKit Agents before 1.4 makes each provider's tools in its plugin")
    try:
        tools = context.parse_function_tools(format)
    except ValueError:
        pytest.skip(f"this LiveKit Agents has no {format} format")
    text = json.dumps(tools, default=str)
    assert len(tools) == 4 and all(name in text for name in TOOL_NAMES) and "email-finder" in text
