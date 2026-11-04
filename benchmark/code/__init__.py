"""Reusable benchmark code for comparing correction strategies.

Nothing in this package imports the V5 application.  The only contact with V5
is reading the selected source images and the authorised API key file, both of
which are read-only.
"""

__all__ = [
    "config",
    "anonymize",
    "loader",
    "keypool",
    "provider",
    "usage",
    "schema",
    "strategies",
    "verifier",
    "evaluator",
    "report",
]
