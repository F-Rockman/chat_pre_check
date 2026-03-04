from __future__ import annotations

from enum import Enum


class DecisionType(str, Enum):
    REFUSE = "refuse"
    CLARIFY = "clarify"
    ROUTE_TEMPLATE = "route_template"
    ROUTE_NL2SQL = "route_nl2sql"
    ROUTE_REPORT = "route_report"


class OutOfScopeReason(str, Enum):
    UNKNOWN_DOMAIN = "unknown_domain"
    UNSUPPORTED_DOMAIN = "unsupported_domain"
    OUT_OF_SEED_SCOPE = "out_of_seed_scope"
    PERMISSION_DENIED = "permission_denied"
    DATA_UNAVAILABLE = "data_unavailable"
    POLICY_BLOCKED = "policy_blocked"
