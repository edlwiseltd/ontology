"""A tiny, safe condition language used throughout the ontology.

Conditions such as ``Customer.industry == 'Financial Services'`` or
``Contract.value > 1000000 and Contract.status == 'approved'`` appear in
action preconditions, goals, rules and tool selectors. They are parsed with
Python's ``ast`` module but only a small whitelist of node types is accepted,
so ontology files can never execute arbitrary code.

Supported:
  * references   ``Entity.attribute``
  * quantifiers  ``all_of(cond)``, ``any_of(cond)``, ``count_of(cond)`` over the instances of a
                 multi-instance entity referenced in ``cond`` (e.g. ``all_of(Order.status == 'placed')``,
                 ``count_of(Order.amount > 1000) >= 2``)
  * literals     strings, numbers, ``True``/``False``/``None``, lists/tuples of literals
  * comparisons  ``== != < <= > >= in not in``
  * boolean      ``and or not``
"""

from __future__ import annotations

import ast
import operator
from functools import lru_cache
from typing import Any, Callable, FrozenSet, List, Optional, Tuple

Resolver = Callable[[str, str], Any]


class ExpressionError(ValueError):
    """Raised when a condition is syntactically invalid or uses forbidden constructs."""


QUANTIFIERS = ("all_of", "any_of", "count_of")
# arithmetic for computed values (ontology functions, computed effects); None in, None out
_ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_MATH = {"min": min, "max": max, "abs": abs, "round": round}


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

    __slots__ = ("source", "_tree", "references", "_qrefs", "quantifiers", "free_references")

    def __init__(self, source: str):
        if not isinstance(source, str) or not source.strip():
            raise ExpressionError("expression must be a non-empty string")
        self.source = source.strip()
        try:
            self._tree = ast.parse(self.source, mode="eval").body
        except SyntaxError as exc:
            raise ExpressionError(f"invalid expression {source!r}: {exc.msg}") from None
        refs: set[Tuple[str, str]] = set()
        free: set[Tuple[str, str]] = set()
        self._qrefs: dict = {}
        self.quantifiers: list = []  # (function, entities referenced inside)
        self._validate(self._tree, refs, free)
        self.references: FrozenSet[Tuple[str, str]] = frozenset(refs)
        self.free_references: FrozenSet[Tuple[str, str]] = frozenset(free)  # outside any quantifier

    # -- validation -----------------------------------------------------
    def _validate(self, node: ast.AST, refs: set, free: Optional[set] = None) -> None:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                self._validate(value, refs, free)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            self._validate(node.operand, refs, free)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _ARITHMETIC:
                raise ExpressionError(f"operator {type(node.op).__name__} not allowed in {self.source!r}")
            self._validate(node.left, refs, free)
            self._validate(node.right, refs, free)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _MATH:
            if node.keywords or not node.args:
                raise ExpressionError(f"{node.func.id}() takes positional arguments only in {self.source!r}")
            for arg in node.args:
                self._validate(arg, refs, free)
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _COMPARATORS:
                    raise ExpressionError(f"operator {type(op).__name__} not allowed in {self.source!r}")
            self._validate(node.left, refs, free)
            for comparator in node.comparators:
                self._validate(comparator, refs, free)
        elif isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.attr.startswith("_"):
                raise ExpressionError(f"references must look like Entity.attribute in {self.source!r}")
            refs.add((node.value.id, node.attr))
            if free is not None:
                free.add((node.value.id, node.attr))
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise ExpressionError(f"literal {node.value!r} not allowed in {self.source!r}")
        elif isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                if not isinstance(elt, ast.Constant):
                    raise ExpressionError(f"collections may only hold literals in {self.source!r}")
                self._validate(elt, refs)
        elif isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in QUANTIFIERS) or node.keywords \
                    or len(node.args) != 1:
                raise ExpressionError(f"only {', '.join(QUANTIFIERS)}(condition) calls are allowed in {self.source!r}")
            inner: set = set()
            self._validate(node.args[0], inner)
            entities = frozenset(e for e, _ in inner)
            if not entities:
                raise ExpressionError(f"{node.func.id}() must reference an entity in {self.source!r}")
            self._qrefs[id(node)] = entities
            self.quantifiers.append((node.func.id, entities))
            refs |= inner
        else:
            raise ExpressionError(f"construct {type(node).__name__} not allowed in {self.source!r}")

    # -- evaluation -----------------------------------------------------
    def evaluate(self, resolve: Resolver) -> bool:
        return bool(self._eval(self._tree, resolve))

    def value(self, resolve: Resolver) -> Any:
        """The expression's value (a number for a computation), not coerced to a truth value."""
        return self._eval(self._tree, resolve)

    @staticmethod
    def _arith(fn: Callable[..., Any], *args: Any) -> Any:
        if any(a is None or isinstance(a, bool) for a in args):
            return None  # unknown in, unknown out
        try:
            return fn(*args)
        except (TypeError, ZeroDivisionError, ValueError):
            return None

    def _eval(self, node: ast.AST, resolve: Resolver) -> Any:
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self._eval(v, resolve) for v in node.values)
            return any(self._eval(v, resolve) for v in node.values)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, resolve)
            if isinstance(node.op, ast.Not):
                return not operand
            return self._arith(operator.neg if isinstance(node.op, ast.USub) else operator.pos, operand)
        if isinstance(node, ast.BinOp):
            return self._arith(_ARITHMETIC[type(node.op)], self._eval(node.left, resolve), self._eval(node.right, resolve))
        if isinstance(node, ast.Call) and node.func.id in _MATH:
            return self._arith(_MATH[node.func.id], *(self._eval(a, resolve) for a in node.args))
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
        if isinstance(node, ast.Call):
            results = [bool(self._eval(node.args[0], scope)) for scope in self._scopes(node, resolve)]
            fn = node.func.id
            if fn == "all_of":
                return all(results)
            if fn == "any_of":
                return any(results)
            return sum(results)
        raise ExpressionError(f"cannot evaluate {type(node).__name__}")  # pragma: no cover

    # -- three-valued evaluation: True, False or None (unknown) -------------------------
    def evaluate_known(self, resolve: Resolver) -> Optional[bool]:
        """Like :meth:`evaluate`, but a comparison on a missing or wrongly typed value is *unknown*
        (``None``) instead of false. Unknown propagates with Kleene logic (``False and unknown`` is False,
        ``True or unknown`` is True). Comparing with an explicit ``None`` literal stays a normal comparison.
        Used for rules that must apply when the facts they depend on are unknown.
        """
        out = self._eval3(self._tree, resolve)
        return None if out is _UNKNOWN else bool(out)

    def unknown_references(self, resolve: Resolver) -> List[str]:
        """``Entity.attr`` references (outside quantifiers) whose value is missing."""
        return [f"{e}.{a}" for e, a in sorted(self.free_references) if resolve(e, a) is None]

    def _eval3(self, node: ast.AST, resolve: Resolver) -> Any:
        if isinstance(node, ast.BoolOp):
            values = [self._truth3(v, resolve) for v in node.values]
            if isinstance(node.op, ast.And):
                return False if False in values else (_UNKNOWN if _UNKNOWN in values else True)
            return True if True in values else (_UNKNOWN if _UNKNOWN in values else False)
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, ast.Not):
            operand = self._eval3(node.operand, resolve)
            return _UNKNOWN if operand in (_UNKNOWN, None) else self._eval(node, resolve)
        if isinstance(node, (ast.BinOp, ast.Call)) and not (isinstance(node, ast.Call) and node.func.id in QUANTIFIERS):
            parts = [node.left, node.right] if isinstance(node, ast.BinOp) else node.args
            values = [self._eval3(p, resolve) for p in parts]
            if any(v is _UNKNOWN or v is None for v in values):
                return _UNKNOWN
            out = self._eval(node, resolve)
            return _UNKNOWN if out is None else out
        if isinstance(node, ast.UnaryOp):
            inner = self._truth3(node.operand, resolve)
            return inner if inner is _UNKNOWN else not inner
        if isinstance(node, ast.Compare):
            left, left_node = self._eval3(node.left, resolve), node.left
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval3(comparator, resolve)
                if _UNKNOWN in (left, right) or (left is None and not _is_none(left_node)) \
                        or (right is None and not _is_none(comparator)):
                    return _UNKNOWN
                try:
                    if not _COMPARATORS[type(op)](left, right):
                        return False
                except TypeError:  # e.g. "80000" >= 50000: a wrongly typed fact is not a fact
                    return _UNKNOWN
                left, left_node = right, comparator
            return True
        if isinstance(node, ast.Call):
            results = [self._truth3(node.args[0], scope) for scope in self._scopes(node, resolve)]
            fn = node.func.id
            if fn == "all_of":
                return False if False in results else (_UNKNOWN if _UNKNOWN in results else True)
            if fn == "any_of":
                return True if True in results else (_UNKNOWN if _UNKNOWN in results else False)
            return _UNKNOWN if _UNKNOWN in results else sum(1 for r in results if r)
        return self._eval(node, resolve)  # attributes, constants, collections: plain values

    def _truth3(self, node: ast.AST, resolve: Resolver) -> Any:
        value = self._eval3(node, resolve)
        if value is _UNKNOWN or (value is None and isinstance(node, ast.Attribute)):
            return _UNKNOWN
        return bool(value)

    def _scopes(self, node: ast.Call, resolve: Resolver) -> list:
        """One resolver per instance of the multi-instance entity the quantifier ranges over."""
        each = getattr(resolve, "each", None)
        if each is not None:
            for entity in sorted(self._qrefs[id(node)]):
                scopes = each(entity)
                if scopes is not None:
                    return scopes
        return [resolve]  # single-instance entity: the quantifier is over that one instance

    def decompose(self) -> Tuple[list, list]:
        """Split a conjunction into ``all_of`` parts and the rest.

        Returns ``([(entities, inner Expression), ...], [Expression, ...])`` - used by the planner to
        plan one instance at a time.
        """
        conjuncts = self._tree.values if isinstance(self._tree, ast.BoolOp) and isinstance(self._tree.op, ast.And) \
            else [self._tree]
        quantified, rest = [], []
        for node in conjuncts:
            source = ast.get_source_segment(self.source, node)
            if isinstance(node, ast.Call) and node.func.id == "all_of":
                inner = compile_expression(ast.get_source_segment(self.source, node.args[0]))
                quantified.append((self._qrefs[id(node)], inner))
            else:
                rest.append(compile_expression(source))
        return quantified, rest

    def deficit(self, resolve: Resolver) -> int:
        """Rough distance from satisfied: failing conjuncts, counting each failing instance of ``all_of``."""
        return self._deficit(self._tree, resolve)

    def _deficit(self, node: ast.AST, resolve: Resolver) -> int:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return sum(self._deficit(v, resolve) for v in node.values)
        if isinstance(node, ast.Call) and node.func.id == "all_of":
            return sum(1 for scope in self._scopes(node, resolve) if not self._eval(node.args[0], scope))
        return 0 if self._eval(node, resolve) else 1

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"

    def __str__(self) -> str:
        return self.source


_UNKNOWN = object()


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


@lru_cache(maxsize=1024)
def compile_expression(source: str) -> Expression:
    """Parse and validate ``source`` (cached)."""
    return Expression(source)
