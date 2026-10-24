"""Idempotent seed data: project, 20 personas, 8 noise profiles, rubric v1, the mock EMI agent with
its scenarios, and the demo API key. Run it with ``python -m pareeksha.seed``."""

from pareeksha.seed.runner import SeedResult, seed_database

__all__ = ["SeedResult", "seed_database"]
