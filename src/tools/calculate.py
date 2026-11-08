# Copyright 2026 Thales
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import math
import operator
import statistics

_MAX_EXPR_CHARS = 2000
_MAX_POW_BITS = 10_000

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _percentile(values, p):
    """Linear-interpolated percentile; p in [0, 100]."""
    if not values:
        raise ValueError("percentile() of an empty list")
    if not 0 <= p <= 100:
        raise ValueError("percentile p must be between 0 and 100")
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _pct_change(old, new):
    if old == 0:
        raise ValueError("pct_change() with old value 0")
    return (new - old) / abs(old) * 100


_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "mean": statistics.fmean,
    "median": statistics.median,
    "stdev": statistics.stdev,
    "pstdev": statistics.pstdev,
    "variance": statistics.variance,
    "percentile": _percentile,
    "pct_change": _pct_change,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numeric literals are allowed")
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"unknown name '{node.id}'")
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(el) for el in node.elts]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            _check_pow(left, right)
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("unsupported function")
        if node.keywords:
            raise ValueError("keyword arguments are not supported")
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def _check_pow(base, exp):
    """Refuse exponentiation that would build a gigantic integer."""
    if isinstance(base, int) and isinstance(exp, int) and exp > 0:
        if base.bit_length() * exp > _MAX_POW_BITS:
            raise ValueError("exponent too large")


class CalculateTool:
    name = "calculate"
    description = (
        "Evaluate a numeric expression exactly. Use this instead of doing arithmetic "
        "yourself. Supports + - * / // % **, parentheses, list literals like [1, 2, 3], "
        "constants pi and e, and the functions: abs, round, min, max, sum, len, sqrt, "
        "log, log10, exp, floor, ceil, mean, median, stdev, pstdev, variance, "
        "percentile(values, p) with p in 0-100, and pct_change(old, new). "
        "Example: pct_change(120, 150) or mean([3, 5, 10]) or round(7 / 3, 2)."
    )
    ui_description = (
        "Lets the LLM do exact arithmetic and statistics (sums, averages, "
        "percentiles, percent change) instead of guessing."
    )

    def setup(self, chunk_path: str) -> None:
        pass  # stateless

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The numeric expression to evaluate.",
                    }
                },
                "required": ["expression"],
            },
        }

    def run(self, args: dict) -> dict:
        expression = str(args.get("expression", "")).strip()
        if not expression:
            return {"error": "expression is required"}
        if len(expression) > _MAX_EXPR_CHARS:
            return {"error": f"expression longer than {_MAX_EXPR_CHARS} characters"}
        try:
            result = _eval(ast.parse(expression, mode="eval"))
        except SyntaxError:
            return {"error": "invalid expression syntax"}
        except ZeroDivisionError:
            return {"error": "division by zero"}
        except (ValueError, TypeError, OverflowError, statistics.StatisticsError) as e:
            return {"error": str(e)}
        if isinstance(result, float) and not math.isfinite(result):
            return {"error": "result is not a finite number"}
        return {"result": result}
