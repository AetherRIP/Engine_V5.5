"""Strategy H: Strategy A as the default, targeted Strategy C escalation on evidence."""

from .config import POLICIES, PolicyConfig, policy
from .runner import StrategyHRunner

__all__ = ["POLICIES", "PolicyConfig", "policy", "StrategyHRunner"]
