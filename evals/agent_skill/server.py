"""Per-scenario stdio host using the unmodified production MCP tool implementation."""

import argparse
from typing import Any

from xp_libs_analytics.mcp.server import create_server

from .fixtures import CLOCK, make_engine
from .scenarios import load_scenarios, vary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--trial", type=int, default=0)
    args = parser.parse_args()
    scenario = load_scenarios(scenario_id=args.scenario)[0]
    if args.seed or args.trial:
        scenario = vary(scenario, args.seed, args.trial)
    engine, handle = make_engine(scenario, isolated=True)
    original = engine.capabilities

    def capabilities() -> dict[str, Any]:
        # Authorized context only; no oracle, expected query or hidden answer.
        return {**original(), "evaluation_dataset": {"name": handle, "clock": CLOCK.isoformat()}}

    engine.capabilities = capabilities
    server = create_server(engine, uploads=False)
    server.run(transport="stdio", show_banner=False, log_level="ERROR")


if __name__ == "__main__":
    main()
