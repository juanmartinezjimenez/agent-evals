"""Evaluate LLM agents against versioned test cases."""

from agent_evals.models import Case, Suite
from agent_evals.runner import RunResult, run_suite

__all__ = ["Case", "RunResult", "Suite", "run_suite"]
__version__ = "0.4.0"
