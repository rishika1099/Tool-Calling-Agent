"""All tools the harness can run, and the JSON that describes them to the model.

Each module exports TOOLS (what the model sees) and TOOL_MAP (what the harness runs).
A tool that declares a `session` parameter gets the caller's Session injected;
the model never sees or fills that argument.
"""

import inspect
import json

from . import forecast, outfit, style, tryon, warmth, wardrobe

_MODULES = [forecast, warmth, outfit, wardrobe, style, tryon]

TOOLS = [tool for module in _MODULES for tool in module.TOOLS]
TOOL_MAP = {name: fn for module in _MODULES for name, fn in module.TOOL_MAP.items()}


def run_tool(name: str, args: dict, session) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    fn = TOOL_MAP[name]
    if "session" in inspect.signature(fn).parameters:
        args = {**args, "session": session}
    try:
        return fn(**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"{name} failed unexpectedly ({type(e).__name__}). Tell the user and try another approach."})
