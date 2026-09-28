from __future__ import annotations

import ast
import math
import re
from collections.abc import Mapping


_NUMBER = re.compile(
    r"^(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)"
    r"(?P<suffix>meg|[tgkmunpf])?$",
    re.IGNORECASE,
)
_FACTORS = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}


def parse_spice_number(text: str) -> float:
    match = _NUMBER.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"不是受支持的 SPICE 数值：{text!r}")
    value = float(match.group("number"))
    suffix = match.group("suffix")
    if suffix:
        value *= _FACTORS[suffix.casefold()]
    if not math.isfinite(value):
        raise ValueError(f"SPICE 数值必须有限：{text!r}")
    return value


def _replace_spice_literals(text: str) -> str:
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.])((?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?(?:meg|[tgkmunpf]))(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    return pattern.sub(lambda match: repr(parse_spice_number(match.group(1))), text)


def evaluate_expression(text: str, values: Mapping[str, float]) -> float:
    expression = text.strip()
    if expression.startswith("{") and expression.endswith("}"):
        expression = expression[1:-1].strip()
    expression = _replace_spice_literals(expression)
    lookup = {name.casefold(): float(value) for name, value in values.items()}

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            key = node.id.casefold()
            if key not in lookup:
                raise KeyError(f"表达式引用了未知参数：{node.id}")
            return lookup[key]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            return left**right
        raise ValueError(f"不允许的表达式语法：{ast.dump(node, include_attributes=False)}")

    try:
        result = visit(ast.parse(expression, mode="eval"))
    except SyntaxError as exc:
        raise ValueError(f"非法参数表达式：{text!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"参数表达式结果必须有限：{text!r}")
    return float(result)


def parse_assignments(text: str) -> dict[str, str]:
    """Parse NAME=EXPR pairs while preserving braces and parenthesized expressions."""
    result: dict[str, str] = {}
    index = 0
    name_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*=")
    matches = list(name_pattern.finditer(text))
    for position, match in enumerate(matches):
        if text[index:match.start()].strip():
            raise ValueError(f"无法解析赋值片段：{text[index:match.start()]!r}")
        name = match.group(0).split("=", 1)[0].strip()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        value = text[match.end():end].strip()
        if not value:
            raise ValueError(f"参数 {name} 缺少值")
        key = name.casefold()
        if key in {item.casefold() for item in result}:
            raise ValueError(f"参数重复定义：{name}")
        result[name] = value
        index = end
    if text[index:].strip():
        raise ValueError(f"无法解析赋值片段：{text[index:]!r}")
    return result


class ParameterEnvironment:
    def __init__(self, expressions: Mapping[str, str]) -> None:
        self._expressions = dict(expressions)
        self._keys = {name.casefold(): name for name in expressions}
        if len(self._keys) != len(self._expressions):
            raise ValueError("参数名称忽略大小写后重复")

    def resolve(self, overrides: Mapping[str, float] | None = None) -> dict[str, float]:
        overrides = overrides or {}
        normalized_overrides = {name.casefold(): float(value) for name, value in overrides.items()}
        unknown = set(normalized_overrides) - set(self._keys)
        if unknown:
            raise KeyError(f"未知参数覆盖：{sorted(unknown)}")
        cache: dict[str, float] = {}
        visiting: set[str] = set()

        def one(key: str) -> float:
            if key in cache:
                return cache[key]
            if key in normalized_overrides:
                value = normalized_overrides[key]
            else:
                if key in visiting:
                    raise ValueError(f"参数表达式存在循环依赖：{self._keys[key]}")
                visiting.add(key)
                expression = self._expressions[self._keys[key]]
                names = {
                    name.id.casefold()
                    for name in ast.walk(ast.parse(_replace_spice_literals(expression.strip("{} ")), mode="eval"))
                    if isinstance(name, ast.Name)
                }
                dependencies = {self._keys[name]: one(name) for name in names if name in self._keys}
                value = evaluate_expression(expression, dependencies)
                visiting.remove(key)
            if not math.isfinite(value):
                raise ValueError(f"参数必须有限：{self._keys[key]}")
            cache[key] = float(value)
            return cache[key]

        return {original: one(key) for key, original in self._keys.items()}
