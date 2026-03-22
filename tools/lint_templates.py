from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from template_capability.config import load_template_config
from template_capability.validation import TemplateConfigValidationError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint template configuration before running the matcher.")
    parser.add_argument("--config", default="configs/templates.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        load_template_config(args.config)
    except TemplateConfigValidationError as error:
        print("Template config validation failed:")
        for item in error.errors:
            print(f"- {item}")
        raise SystemExit(1)
    print(f"Template config is valid: {args.config}")


if __name__ == "__main__":
    main()
