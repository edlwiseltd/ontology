"""A tiny, safe condition language used throughout the ontology.

Conditions such as ``Customer.industry == 'Financial Services'`` or
``Contract.value > 1000000 and Contract.status == 'approved'`` appear in
action preconditions, goals, rules and tool selectors. They are parsed with
Python's ``ast`` module but only a small whitelist of node types is accepted,
so ontology files can never execute arbitrary code.

Supported:
  * references   ``Entity.attribute``
  * literals     strings, numbers, ``True``/``False``/``None``, lists/tuples of literals
  * comparisons  ``== != < <= > >= in not in``
  * boolean      ``and or not``
"""

from __future__ import annotations

import ast
import operator
from functools import lru_cache
from typing import Any, Callable, FrozenSet, Tuple

Resolver = Callable[[str, str], Any]


class ExpressionError(ValueError):
    """Raised when a condition is syntactically invalid or uses forbidden constructs."""


_COMPARATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


class Expression:
    """A validated, reusable condition."""

    __slots__ = ("source", "_tree", "references")

    def __init__(self, source: str):
        if not isinstance(source, str) or not source.strip():
            raise ExpressionError("expression must be a non-empty string")
        self.source = source.strip()
        try:
            self._tree = ast.parse(self.source, mode="eval").body
        except SyntaxError as exc:
            raise ExpressionError(f"invalid expression {source!r}: {exc.msg}") from None
        refs: set[Tuple[str, str]] = set()
        self._validate(self._tree, refs)
        self.references: FrozenSet[Tuple[str, str]] = frozenset(refs)

    # -- validation -----------------------------------------------------
    def _validate(self, node: ast.AST, refs: set) -> None:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                self._validate(value, refs)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self._validate(node.operand, refs)
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _COMPARATORS:
                    raise ExpressionError(f"operator {type(op).__name__} not allowed in {self.source!r}")
            self._validate(node.left, refs)
            for comparator in node.comparators:
                self._validate(comparator, refs)
        elif isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.attr.startswith("_"):
                raise ExpressionError(f"references must look like Entity.attribute in {self.source!r}")
            refs.add((node.value.id, node.attr))
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise ExpressionError(f"literal {node.value!r} not allowed in {self.source!r}")
        elif isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                if not isinstance(elt, ast.Constant):
                    raise ExpressionError(f"collections may only hold literals in {self.source!r}")
                self._validate(elt, refs)
        else:
            raise ExpressionError(f"construct {type(node).__name__} not allowed in {self.source!r}")

    # -- evaluation -----------------------------------------------------
    def evaluate(self, resolve: Resolver) -> bool:
        return bool(self._eval(self._tree, resolve))

    def _eval(self, node: ast.AST, resolve: Resolver) -> Any:
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self._eval(v, resolve) for v in node.values)
            return any(self._eval(v, resolve) for v in node.values)
        if isinstance(node, ast.UnaryOp):
            return not self._eval(node.operand, resolve)
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, resolve)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, resolve)
                try:
                    if not _COMPARATORS[type(op)](left, right):
                        return False
                except TypeError:  # e.g. None > 5 -> condition simply does not hold
                    return False
                left = right
            return True
        if isinstance(node, ast.Attribute):
            return resolve(node.value.id, node.attr)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return tuple(self._eval(e, resolve) for e in node.elts)
        raise ExpressionError(f"cannot evaluate {type(node).__name__}")  # pragma: no cover

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"

    def __str__(self) -> str:
        return self.source


@lru_cache(maxsize=1024)
def compile_expression(source: str) -> Expression:
    """Parse and validate ``source`` (cached)."""
    return Expression(source)
