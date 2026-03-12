from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.demo.local_runtime import build_local_fallback_engine
from chat_pre_check.demo.runtime import print_route_summary, route_payload
from chat_pre_check.infrastructure.config.loader import load_app_config
from chat_pre_check.infrastructure.resolvers.search_client_factory import (
    build_search_client,
)


DEFAULT_OS_URL = "http://localhost:9200"

DEMO_INPUTS = [
    "近24小时接口错误包告警Top10",
    "查1天内告警Top10的接口错误包",
    "查询最近接口异常包告警Top5",
    "近7天华东BGP flap Top20",
    "近24小时设备CPU利用率Top10",
    "近30天华北骨干网抖动与丢包相关性",
    "昨天离线设备数",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-click local live runner (search backend first, fallback supported)."
    )
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--os-url", default=DEFAULT_OS_URL)
    parser.add_argument(
        "--search-backend",
        choices=["opensearch", "elasticsearch", "es"],
        default=None,
        help="Search backend type. Default reads CHAT_PRE_CHECK_SEARCH_BACKEND or vector.search_backend.",
    )
    parser.add_argument("--trace-level", choices=["compact", "debug"], default="compact")
    parser.add_argument("--role", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--input", default="")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument(
        "--without-opensearch",
        "--without-search-backend",
        dest="without_opensearch",
        action="store_true",
        help="Force search-backend-free local fallback mode.",
    )
    parser.add_argument(
        "--require-opensearch",
        "--require-search-backend",
        dest="require_opensearch",
        action="store_true",
        help="Exit if search backend is not reachable.",
    )
    parser.add_argument("--show-trace", action="store_true")
    return parser.parse_args()


def select_engine(args: argparse.Namespace):
    if args.without_opensearch:
        print("[livemain] run_mode=local_fallback (forced)")
        return build_local_fallback_engine(config_dir=args.config_dir)

    ready, reason, backend = _search_backend_ready(
        args.os_url,
        args.config_dir,
        search_backend=args.search_backend,
    )
    if ready:
        print(f"[livemain] run_mode={backend}_live url={args.os_url}")
        return build_engine(
            config_dir=args.config_dir,
            os_url=args.os_url,
            search_backend=args.search_backend,
            os_username=os.getenv("CHAT_PRE_CHECK_OS_USERNAME"),
            os_password=os.getenv("CHAT_PRE_CHECK_OS_PASSWORD"),
            os_bearer_token=os.getenv("CHAT_PRE_CHECK_OS_BEARER_TOKEN"),
        )

    if args.require_opensearch:
        raise SystemExit(
            f"Search backend not ready ({reason}). "
            "Use --without-opensearch to run fallback mode."
        )

    print(f"[livemain] run_mode=local_fallback (search backend not ready: {reason})")
    return build_local_fallback_engine(config_dir=args.config_dir)


def _search_backend_ready(
    url: str,
    config_dir: str,
    *,
    search_backend: str | None,
) -> tuple[bool, str, str]:
    try:
        config = load_app_config(config_dir)
        vector_cfg = config.vector
        backend, client = build_search_client(
            vector_cfg=vector_cfg,
            base_url=url,
            backend_override=search_backend,
            timeout=2,
            max_retries=0,
        )
        if not client.ping():
            return False, "ping_failed", backend
        required_indices = [
            vector_cfg.get("scene_index"),
            vector_cfg.get("template_index"),
            vector_cfg.get("device_index", "assets_device_v1"),
            vector_cfg.get("region_index", "assets_region_v1"),
        ]
        missing = [
            idx
            for idx in required_indices
            if idx and not client.index_exists(idx)
        ]
        if missing:
            return False, f"missing_indices={','.join(missing)}", backend
        return True, "ok", backend
    except Exception as exc:
        return False, f"exception={exc}", "unknown"


def run_one(engine, text: str, args: argparse.Namespace) -> None:
    payload = route_payload(
        engine,
        text,
        role=args.role,
        tenant_id=args.tenant_id,
        trace_level=args.trace_level,
    )
    print_route_summary(text, payload, show_trace=args.show_trace)


def run_interactive(engine, args: argparse.Namespace) -> None:
    print("Interactive mode. 输入 exit 退出。")
    while True:
        text = input(">>> ").strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            break
        run_one(engine, text, args)


def run_batch(engine, args: argparse.Namespace) -> None:
    if args.input:
        run_one(engine, args.input, args)
        return
    for text in DEMO_INPUTS:
        run_one(engine, text, args)


def main() -> None:
    args = parse_args()
    engine = select_engine(args)
    if args.interactive:
        run_interactive(engine, args)
    else:
        run_batch(engine, args)


if __name__ == "__main__":
    main()
