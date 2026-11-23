# livekit-agents-datacircle

Find the best GTM APIs. We benchmark all the GTM APIs and we put the results on our website.

Our website: https://datacircle.dev

This package gives [LiveKit Agents](https://github.com/livekit/agents) four function tools that call Datacircle's public API, https://api.datacircle.dev/v1. You need no key and no account.

| Tool | Gives | Call |
| --- | --- | --- |
| `datacircle_list_apis` | Every GTM API on Datacircle, with the API's slug, number of plans, number of providers and best plan | `GET /apis` |
| `datacircle_best_plans` | One API's plans, sorted by score out of 100, best first. Each plan comes with a rank and a price per 1,000 calls | `GET /apis/{slug}/best` |
| `datacircle_search_plans` | Plans that match a provider or plan name, on all APIs or on one API. You can sort them by score, provider or price | `GET /plans` |
| `datacircle_provider` | The APIs a provider sells, and the provider's rank on each API | `GET /providers/{slug}` |

## Install

```bash
pip install livekit-agents-datacircle
```

The package needs LiveKit Agents 1.0.15 or later (`livekit-agents`) and Python 3.10 or later.

## Give the tools to your agent

```python
from livekit.agents import Agent
from livekit_agents_datacircle import datacircle_tools

agent = Agent(
    instructions="You help the user find the best GTM API for their needs.",
    tools=datacircle_tools(),
)
```

Start the agent in your `AgentSession`. LiveKit turns the tools into each LLM provider's format.

To add the tools beside your own, list them: `tools=[lookup_weather, *datacircle_tools()]`.

To give only some of the tools, list their names: `datacircle_tools(["datacircle_best_plans"])`.

On LiveKit Agents 1.4 or later, you can give the tools as one toolset: `tools=[DatacircleToolset()]`.

## Call a tool yourself

`run` returns a tool's output for the model:

```python
from livekit_agents_datacircle import run

print(run("datacircle_best_plans", {"slug": "email-finder", "limit": 3}))
```

## Tool output for the model

Each tool gives the model our API's answer as JSON. Each plan comes with a rank, provider, plan, score, price per 1,000 (`perThousand`, in dollars) and a page on datacircle.dev. That page lists every field.

You can give a provider's name in place of a slug. The tool turns `Bright Data` into `bright-data`.

The tool raises a `ToolError` with the API's error message when the model passes an unknown slug. LiveKit gives the model this message. The error for an unknown API slug lists every valid slug. The model can then pick one and call the tool again. The tool checks each number from the model before the API call. The model gets an error message for any number out of range. The tool doesn't call the API for that number.

## Network

Each tool call makes one HTTPS GET request to https://api.datacircle.dev/v1 and no other network calls. The request runs in a thread, so your agent keeps running. The request holds only the tool's own arguments. The API takes up to 60 calls a minute from one IP address. If the API says to wait, the tool waits up to a minute. The tool waits once per call, no more. All plans are in one file at https://datacircle.dev/datacircle.json.

## Links

- Datacircle: https://datacircle.dev
- The API: https://datacircle.dev/api
- The API's spec: https://api.datacircle.dev/v1/openapi.json
- What each key means: https://datacircle.dev/fields

MIT license.
