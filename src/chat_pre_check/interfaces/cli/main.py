from __future__ import annotations

import argparse
import json

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.domain.models import RouteRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="chat_pre_check CLI")
    parser.add_argument("text", help="User input text")
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--trace-level", default="compact", choices=["compact", "debug"])
    parser.add_argument("--role", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--os-url", default=None)
    parser.add_argument(
        "--search-backend",
        choices=["opensearch", "elasticsearch", "es"],
        default=None,
    )
    args = parser.parse_args()

    engine = build_engine(
        config_dir=args.config_dir,
        os_url=args.os_url,
        search_backend=args.search_backend,
    )
    decision = engine.route(
        RouteRequest(
            input_text=args.text,
            role=args.role,
            tenant_id=args.tenant_id,
            trace_level=args.trace_level,
        )
    )
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
