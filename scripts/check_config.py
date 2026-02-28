from __future__ import annotations

import argparse

from chat_pre_check.infrastructure.config.loader import load_app_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate chat_pre_check config files")
    parser.add_argument("--config-dir", default="configs")
    args = parser.parse_args()
    load_app_config(args.config_dir)
    print("config_ok")


if __name__ == "__main__":
    main()
