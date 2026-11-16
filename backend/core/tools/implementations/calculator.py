"""
Tool 1: Calculator
Evaluates mathematical expressions safely using Python's AST module.
Strictly disallows eval, exec, imports, attribute lookups, and arbitrary code execution.
"""

import ast
import math
import operator
from typing import Any, Dict, Union
from pydantic import BaseModel, Field

from backend.core.tools.base import BaseTool, PermissionLevel, SecurityBoundaryError, ToolContext

_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_MATH_FUNCTIONS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
    "pow": math.pow,
    "min": min,
    "max": max,
}

_SAFE_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

class CalculatorInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=500, description="Mathematical expression (e.g., '(14.5 * 2.8) + sqrt(144) - log(100)')")

class CalculatorOutput(BaseModel):
    expression: str
    result: Union[float, int]
    formatted: str

class CalculatorTool(BaseTool):
    id = "calculator"
    name = "Safe Mathematical Calculator"
    description = (
        "Evaluates mathematical expressions safely via an AST evaluator supporting arithmetic, "
        "powers, trigonometry, and logarithms. Strictly isolates execution from system shells or arbitrary code."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds = 5.0
    input_schema = CalculatorInput
    output_schema = CalculatorOutput

    async def execute(self, params: CalculatorInput, context: ToolContext) -> CalculatorOutput:
        parsed_ast = self._parse_and_validate(params.expression)
        val = self._evaluate_node(parsed_ast.body)
        
        # Check for non-finite values
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            raise ValueError(f"Calculation resulted in non-finite value: {val}")

        return CalculatorOutput(
            expression=params.expression,
            result=val,
            formatted=f"{val:,.6g}" if isinstance(val, float) else f"{val:,}"
        )

    def _parse_and_validate(self, expression: str) -> ast.Expression:
        # Prevent oversized expressions
        if len(expression) > 500:
            raise SecurityBoundaryError("Expression exceeds maximum character limit of 500.")

        # Ban suspicious tokens
        banned = ["__", "lambda", "import", "exec", "eval", "os", "sys", "open", "subprocess"]
        expr_lower = expression.lower()
        for b in banned:
            if b in expr_lower:
                raise SecurityBoundaryError(f"Security restriction: token '{b}' is forbidden in calculator expressions.")

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid mathematical expression syntax: {e}")

        return tree

    def _evaluate_node(self, node: ast.AST) -> Union[int, float]:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Disallowed constant type in calculation: {type(node.value).__name__}")

        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _SAFE_OPERATORS:
                raise SecurityBoundaryError(f"Disallowed unary operator: {op_type.__name__}")
            operand = self._evaluate_node(node.operand)
            return _SAFE_OPERATORS[op_type](operand)

        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _SAFE_OPERATORS:
                raise SecurityBoundaryError(f"Disallowed binary operator: {op_type.__name__}")
            left = self._evaluate_node(node.left)
            right = self._evaluate_node(node.right)

            # Prevent resource exhaustion from gigantic exponents (e.g. 10 ** 100000)
            if op_type == ast.Pow:
                if abs(right) > 1000:
                    raise SecurityBoundaryError("Exponent magnitude exceeds safety threshold of 1000.")
                if abs(left) > 1e10 and right > 10:
                    raise SecurityBoundaryError("Power calculation will overflow safe numeric boundaries.")

            if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
                raise ZeroDivisionError("Division or modulo by zero.")

            return _SAFE_OPERATORS[op_type](left, right)

        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise SecurityBoundaryError("Dynamic or attributed function calls are strictly prohibited.")
            func_name = node.func.id
            if func_name not in _SAFE_MATH_FUNCTIONS:
                raise SecurityBoundaryError(f"Function '{func_name}' is not in the approved math whitelist.")

            args = [self._evaluate_node(a) for a in node.args]
            return _SAFE_MATH_FUNCTIONS[func_name](*args)

        elif isinstance(node, ast.Name):
            name = node.id
            if name in _SAFE_CONSTANTS:
                return _SAFE_CONSTANTS[name]
            raise SecurityBoundaryError(f"Unknown or unwhitelisted identifier: '{name}'.")

        raise SecurityBoundaryError(f"Disallowed AST expression element: {type(node).__name__}")
