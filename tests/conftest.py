from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat_pre_check.bootstrap import build_engine
from tests.fixtures.fakes import FakeDeviceResolver, FakeRegionResolver, FakeVectorRetriever


def pytest_addoption(parser):
    parser.addoption(
        "--os-base-url",
        action="store",
        default="http://localhost:9200",
        help="OpenSearch base URL for integration tests.",
    )


@pytest.fixture(scope="session")
def os_base_url(pytestconfig):
    return pytestconfig.getoption("--os-base-url")


@pytest.fixture(scope="session")
def test_engine():
    return build_engine(
        config_dir=str(ROOT / "configs"),
        retriever_override=FakeVectorRetriever(),
        device_resolver_override=FakeDeviceResolver(),
        region_resolver_override=FakeRegionResolver(),
    )
