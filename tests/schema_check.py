"""The JSON Schema checker used by the contract tests. It now lives in the package (:mod:`autology.schema`),
where the AI gateway uses it on model answers; this name is kept for the tests that import it."""

from autology.schema import TYPES, errors

__all__ = ["TYPES", "errors"]
