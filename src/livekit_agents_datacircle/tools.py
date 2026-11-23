"""LiveKit Agents function tools on Datacircle's open API, https://api.datacircle.dev/v1: no key, no account.

Each tool is a function tool with a raw JSON schema, made by LiveKit's own function_tool, for an Agent's tools (or an
AgentSession's). A tool makes one HTTPS GET, off the event loop, and gives the model the API's answer as JSON. A
refusal (an unknown slug, an argument out of range, the API out of reach) is raised as a ToolError in the API's words,
which LiveKit gives the model, so it can call again. LiveKit checks no argument of a raw tool, so each tool checks its
own before any call.
"""

import asyncio
import json
import urllib.parse
from typing import Any, Dict, List, Optional

from livekit.agents import llm
from livekit.agents.llm import ToolError, function_tool

from livekit_agents_datacircle import _api


def _best(plans: Any) -> Optional[Dict[str, Any]]:
    """A provider's best plan on an API: its lowest rank, a plan with no score having none."""
    ranked = sorted(plans, key=lambda plan: plan.get("rank") if isinstance(plan.get("rank"), (int, float)) else float("inf"))
    return _api.brief(ranked[0], ["plan", "score", "perThousand", "page"]) if ranked else None


def list_apis(query: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    count = _api.whole("limit", limit, 1, 200) or 20
    apis = _api.get("/apis")
    words = [word for word in str(query or "").lower().replace("-", " ").split() if word]
    held = []
    for index, api in enumerate(apis):
        name = f"{api.get('api', '')} {str(api.get('slug', '')).replace('-', ' ')}".lower()
        matched = sum(word in name for word in words)
        if matched or not words:
            held.append((-matched, index, api))
    found = [_api.brief(api, _api.API_KEYS) for _, _, api in sorted(held, key=lambda h: h[:2])]
    return {"total": len(found), "apis": found[:count]}


def best_plans(slug: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    made = _api.slug(slug)
    if not made:
        raise _api.DatacircleError("Give an API's slug, like 'email-finder': datacircle_list_apis gives every slug")
    answer = _api.get(f"/apis/{urllib.parse.quote(made)}/best", {"limit": _api.whole("limit", limit, 1, 50)})
    return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}


def search_plans(api: Optional[str] = None, query: Optional[str] = None, sort: Optional[str] = None,
                 limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
    order = str(sort).strip().lower() if sort not in (None, "") else None
    if order is not None and order not in ("score", "provider", "price"):
        raise _api.DatacircleError(f"sort must be score, provider or price, not {sort!r}")
    params = {"api": api, "query": query, "sort": order, "limit": _api.whole("limit", limit, 1, 50),
              "offset": _api.whole("offset", offset, 0)}
    answer = _api.get("/plans", params)
    return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}


def provider(slug: Optional[str] = None) -> Dict[str, Any]:
    made = _api.slug(slug)
    if not made:
        raise _api.DatacircleError("Give a provider's slug or name, like 'bright-data' or 'Bright Data'")
    answer = _api.get(f"/providers/{urllib.parse.quote(made)}")
    apis = [{**_api.brief(entry, ["api", "slug", "rank", "bestPage"]), "plans": len(entry.get("plans") or []),
             "best": _best(entry.get("plans") or [])} for entry in answer.get("apis") or []]
    return {**answer, "apis": apis}


_PRICE = "perThousand is a plan's price of 1,000 items in dollars, pay the plan's whole price in its currency."
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 50, "description": "How many plans to give, 1 to 50. 10 when left out."}

# Each tool: its description, its parameters (JSON schema properties), the ones it needs, and its function.
_TOOLS: Dict[str, Any] = {
    "datacircle_list_apis": (
        "Lists the GTM APIs on Datacircle's sheet (https://datacircle.dev), with each API's slug, how many plans and "
        "providers it has and its best plan. Call it first to find an API's slug. Gives total, the APIs found, and "
        "apis, up to limit of them.",
        {
            "query": {"type": "string", "description": "Words of the API's name or slug, like 'email' or 'linkedin "
                                                       "profile': the APIs that hold the most of them come first. The "
                                                       "sheet's order when left out."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200,
                      "description": "How many APIs to give, 1 to 200. 20 when left out: the sheet has about 160."},
        },
        [],
        list_apis,
    ),
    "datacircle_best_plans": (
        "Gives an API's plans best first by their score out of 100 on Datacircle's benchmark (https://datacircle.dev), "
        "each with its rank, provider, plan, $ per 1,000 calls and its page: the best providers of an API. " + _PRICE,
        {
            "slug": {"type": "string", "description": "The API's slug, like 'email-finder' or 'linkedin-profile', as "
                                                      "datacircle_list_apis gives it."},
            "limit": _LIMIT,
        },
        ["slug"],
        best_plans,
    ),
    "datacircle_search_plans": (
        "Searches every plan on Datacircle's sheet (https://datacircle.dev), or one API's, by provider or plan name, "
        "sorted by score, provider or price. Gives total, offset and up to limit plans. " + _PRICE,
        {
            "api": {"type": "string", "description": "Only this API's plans: its name or slug, like 'email-finder'. A "
                                                     "provider's name goes in query, never here. Every API when left out."},
            "query": {"type": "string", "description": "Words that must all appear in the provider's or plan's name, "
                                                       "like 'bright data'."},
            "sort": {"type": "string", "enum": ["score", "provider", "price"],
                     "description": "score (best first, the default), provider (A to Z) or price ($ per 1,000, lowest first)."},
            "limit": _LIMIT,
            "offset": {"type": "integer", "minimum": 0, "description": "How many found plans to skip first. 0 when left out."},
        },
        [],
        search_plans,
    ),
    "datacircle_provider": (
        "Gives each API one provider sells and its rank on each on Datacircle's benchmark (https://datacircle.dev), "
        "with its best plan there.",
        {
            "slug": {"type": "string", "description": "The provider's slug, like 'bright-data', or its name, like "
                                                      "'Bright Data': the name is made a slug."},
        },
        ["slug"],
        provider,
    ),
}
TOOL_NAMES = list(_TOOLS)


def _known(name: str) -> None:
    if name not in _TOOLS:
        raise ValueError(f"Datacircle has no tool {name!r}: its tools are {', '.join(TOOL_NAMES)}")


def _answer(name: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The API's answer for these arguments, or a DatacircleError. Arguments the tool doesn't take are left out."""
    _known(name)
    _, properties, _, function = _TOOLS[name]
    given = arguments if isinstance(arguments, dict) else {}
    return function(**{key: given.get(key) for key in properties})


def run(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a tool gives the model for these arguments, as a dict: the API's answer, or {"error": its words}."""
    try:
        return _answer(name, arguments)
    except _api.DatacircleError as error:
        return {"error": str(error)}


def datacircle_tool(name: str) -> Any:
    """One of the four tools, by its name: a new function tool, for an Agent's tools."""
    _known(name)
    description, properties, required, _ = _TOOLS[name]

    # A new function for each tool made: LiveKit before 1.4 marks the function itself as a tool.
    async def tool(raw_arguments: Dict[str, Any]) -> str:
        try:
            answer = await asyncio.to_thread(_answer, name, raw_arguments)
        except _api.DatacircleError as error:
            raise ToolError(str(error)) from None
        return json.dumps(answer, ensure_ascii=False)

    tool.__name__ = tool.__qualname__ = name
    tool.__doc__ = description
    schema = {"name": name, "description": description,
              "parameters": {"type": "object", "properties": json.loads(json.dumps(properties)), "required": list(required)}}
    return function_tool(tool, raw_schema=schema)


def datacircle_tools(tool_names: Optional[List[str]] = None) -> List[Any]:
    """The tools as a list, for Agent(tools=datacircle_tools()) or beside tools of one's own. tool_names keeps some of
    them only, in their order here; all four when left out."""
    if isinstance(tool_names, str):
        raise TypeError("tool_names is a list of names, like ['datacircle_best_plans']")
    return [datacircle_tool(name) for name in (TOOL_NAMES if tool_names is None else tool_names)]


_Toolset: Any = getattr(llm, "Toolset", None)

if _Toolset is not None:

    class DatacircleToolset(_Toolset):  # type: ignore[misc, valid-type]
        """The tools as one Toolset, id 'datacircle', for Agent(tools=[DatacircleToolset()]): LiveKit Agents 1.4 and
        later. tool_names keeps some of them only; all four when left out."""

        def __init__(self, tool_names: Optional[List[str]] = None) -> None:
            self._datacircle_tools = datacircle_tools(tool_names)
            super().__init__(id="datacircle")

        @property
        def tools(self) -> List[Any]:
            return list(self._datacircle_tools)

else:

    class DatacircleToolset:  # type: ignore[no-redef]
        """LiveKit Agents before 1.4 has no Toolset: give datacircle_tools() to the Agent."""

        def __init__(self, tool_names: Optional[List[str]] = None) -> None:
            raise ImportError("DatacircleToolset needs livekit-agents 1.4 or later: give the Agent datacircle_tools()")


__all__: List[str] = ["DatacircleToolset", "TOOL_NAMES", "best_plans", "datacircle_tool", "datacircle_tools",
                      "list_apis", "provider", "run", "search_plans"]
