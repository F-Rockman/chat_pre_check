from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.interfaces.api.router import get_router


@lru_cache(maxsize=1)
def _engine_singleton():
    """进程内单例引擎，避免重复构建模型与配置对象。"""
    return build_engine(
        config_dir=os.getenv("CHAT_PRE_CHECK_CONFIG_DIR", "configs"),
        os_url=os.getenv("CHAT_PRE_CHECK_OS_URL"),
        search_backend=os.getenv("CHAT_PRE_CHECK_SEARCH_BACKEND"),
        os_username=os.getenv("CHAT_PRE_CHECK_OS_USERNAME"),
        os_password=os.getenv("CHAT_PRE_CHECK_OS_PASSWORD"),
        os_bearer_token=os.getenv("CHAT_PRE_CHECK_OS_BEARER_TOKEN"),
    )


def create_app(engine_override=None) -> FastAPI:
    """创建 FastAPI 应用，可注入测试引擎覆盖默认单例。"""
    app = FastAPI(title="chat_pre_check")

    def engine_provider():
        return engine_override or _engine_singleton()

    app.include_router(get_router(engine_provider))
    return app
