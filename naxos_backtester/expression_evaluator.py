"""Safe AST Expression Evaluator for L2 Microstructure Custom Rules.

Safely compiles and evaluates quantitative microstructure rules against
real-time Level 2 order book frames without unsafe eval() or arbitrary code execution.
"""

from __future__ import annotations

import ast
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Permitted microstructure variable names available on every L2 frame
ALLOWED_MICROSTRUCTURE_VARS: Set[str] = {
    "mid_price_cents",
    "spread_bps",
    "obi_top5",
    "net_arb_cents",
    "vwap_divergence_cents",
    "top5_liquidity_usd",
    "wire_lag_ms",
    "kalshi_fee_bps",
}

# Permitted AST node types (strictly arithmetic, comparison, and boolean logic)
ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Gt,
    ast.Lt,
    ast.GtE,
    ast.LtE,
    ast.Eq,
    ast.NotEq,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
)


class SafeExpressionEvaluator:
    """Zero-eval safe AST parser and runtime evaluator for quantitative trading formulas."""

    @classmethod
    def validate(cls, expr_str: str) -> Tuple[bool, Optional[str]]:
        """Validate whether an expression contains only permitted syntax and variables.

        Returns (is_valid, error_message).
        """
        if not expr_str or not expr_str.strip():
            return False, "Expression is empty."

        clean_expr = expr_str.strip()
        # Normalize uppercase boolean keywords AND/OR/NOT to lowercase for python ast
        # Note: replace only standalone words
        normalized = clean_expr
        tokens = normalized.split()
        normalized_tokens = []
        for t in tokens:
            t_upper = t.upper()
            if t_upper == "AND":
                normalized_tokens.append("and")
            elif t_upper == "OR":
                normalized_tokens.append("or")
            elif t_upper == "NOT":
                normalized_tokens.append("not")
            elif t_upper == "&&":
                normalized_tokens.append("and")
            elif t_upper == "||":
                normalized_tokens.append("or")
            elif t_upper == "!":
                normalized_tokens.append("not")
            else:
                normalized_tokens.append(t)
        normalized = " ".join(normalized_tokens)

        try:
            tree = ast.parse(normalized, mode="eval")
        except SyntaxError as e:
            return False, f"Syntax error: {e.msg} at position {e.offset}"
        except Exception as e:
            return False, f"Parse error: {e}"

        # Ensure root node is a comparison or boolean logic condition
        is_bool_expr = isinstance(tree.body, (ast.Compare, ast.BoolOp)) or (
            isinstance(tree.body, ast.UnaryOp) and isinstance(tree.body.op, ast.Not)
        )
        if not is_bool_expr:
            return False, "Expression must be a comparison or boolean condition returning True or False."

        for node in ast.walk(tree):
            if not isinstance(node, ALLOWED_AST_NODES):
                return False, f"Disallowed syntax node '{type(node).__name__}'. Only comparisons and arithmetic allowed."
            if isinstance(node, ast.Name):
                if node.id not in ALLOWED_MICROSTRUCTURE_VARS:
                    return False, f"Unknown or disallowed variable '{node.id}'. Permitted: {sorted(list(ALLOWED_MICROSTRUCTURE_VARS))}"

        return True, None

    @classmethod
    def evaluate(cls, expr_str: str, context: Dict[str, float]) -> bool:
        """Safely evaluate an expression string against numeric context variables."""
        if not expr_str or not expr_str.strip():
            return False

        clean_expr = expr_str.strip()
        tokens = clean_expr.split()
        normalized_tokens = []
        for t in tokens:
            t_upper = t.upper()
            if t_upper in ("AND", "&&"):
                normalized_tokens.append("and")
            elif t_upper in ("OR", "||"):
                normalized_tokens.append("or")
            elif t_upper in ("NOT", "!"):
                normalized_tokens.append("not")
            else:
                normalized_tokens.append(t)
        normalized = " ".join(normalized_tokens)

        try:
            tree = ast.parse(normalized, mode="eval")
        except Exception:
            return False

        try:
            res = cls._eval_node(tree.body, context)
            return bool(res)
        except Exception as e:
            logger.debug("Evaluation error for '%s': %s", expr_str, e)
            return False

    @classmethod
    def _eval_node(cls, node: ast.AST, context: Dict[str, float]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            return float(context.get(node.id, 0.0))
        elif isinstance(node, ast.UnaryOp):
            val = cls._eval_node(node.operand, context)
            if isinstance(node.op, ast.Not):
                return not val
            elif isinstance(node.op, ast.USub):
                return -val
            elif isinstance(node.op, ast.UAdd):
                return +val
        elif isinstance(node, ast.BinOp):
            left = cls._eval_node(node.left, context)
            right = cls._eval_node(node.right, context)
            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                return left / right if right != 0 else 0.0
            elif isinstance(node.op, ast.Mod):
                return left % right if right != 0 else 0.0
        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(cls._eval_node(v, context) for v in node.values)
            elif isinstance(node.op, ast.Or):
                return any(cls._eval_node(v, context) for v in node.values)
        elif isinstance(node, ast.Compare):
            left = cls._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = cls._eval_node(comparator, context)
                if isinstance(op, ast.Gt) and not (left > right):
                    return False
                elif isinstance(op, ast.Lt) and not (left < right):
                    return False
                elif isinstance(op, ast.GtE) and not (left >= right):
                    return False
                elif isinstance(op, ast.LtE) and not (left <= right):
                    return False
                elif isinstance(op, ast.Eq) and not (abs(left - right) < 1e-9):
                    return False
                elif isinstance(op, ast.NotEq) and not (abs(left - right) >= 1e-9):
                    return False
                left = right
            return True
        return False


def extract_l2_frame_context(frame: Dict[str, Any]) -> Dict[str, float]:
    """Compute normalized quantitative metrics from an L2 frame for rule evaluation."""
    leg_a = frame.get("leg_a") or {}
    leg_b = frame.get("leg_b") or {}

    bids_a = leg_a.get("bids") or frame.get("bids") or []
    asks_a = leg_a.get("asks") or frame.get("asks") or []

    # Best prices
    best_bid = float(bids_a[0][0]) if bids_a else float(frame.get("best_bid", 0.49))
    best_ask = float(asks_a[0][0]) if asks_a else float(frame.get("best_ask", 0.51))

    mid_p = (best_bid + best_ask) / 2.0
    mid_cents = round(mid_p * 100.0, 2)
    spread_bps = round(abs(best_ask - best_bid) * 10000.0, 2)

    # Top-5 depths
    top5_bids = bids_a[:5]
    top5_asks = asks_a[:5]

    bid_depth = sum(float(lvl[1]) for lvl in top5_bids) if top5_bids else 5000.0
    ask_depth = sum(float(lvl[1]) for lvl in top5_asks) if top5_asks else 5000.0
    total_depth = bid_depth + ask_depth

    obi_top5 = round((bid_depth - ask_depth) / total_depth, 4) if total_depth > 0 else 0.0

    # Top-5 Liquidity in USD
    bid_usd = sum(float(lvl[0]) * float(lvl[1]) for lvl in top5_bids) if top5_bids else 2500.0
    ask_usd = sum(float(lvl[0]) * float(lvl[1]) for lvl in top5_asks) if top5_asks else 2500.0
    top5_liquidity_usd = round(bid_usd + ask_usd, 2)

    # Net Arb Cents if leg_b exists
    asks_b = leg_b.get("asks") or []
    best_ask_b = float(asks_b[0][0]) if asks_b else 0.51
    # Raw spread = 1.00 - (ask_a + ask_b + fees)
    fee_a = 0.07 * best_ask * (1.0 - best_ask) if leg_a.get("venue", "").upper() == "KALSHI" else 0.001
    fee_b = 0.07 * best_ask_b * (1.0 - best_ask_b) if leg_b.get("venue", "").upper() == "KALSHI" else 0.001
    net_arb = max(0.0, 1.0 - (best_ask + best_ask_b + fee_a + fee_b))
    net_arb_cents = round(net_arb * 100.0, 2)

    # VWAP Divergence
    vwap_num = sum(float(lvl[0]) * float(lvl[1]) for lvl in top5_bids + top5_asks)
    vwap_den = total_depth
    vwap = (vwap_num / vwap_den) if vwap_den > 0 else mid_p
    vwap_divergence_cents = round((mid_p - vwap) * 100.0, 2)

    wire_lag_ms = float(frame.get("wire_lag_ms", 15.0))
    p_clamped = max(0.01, min(0.99, mid_p))
    kalshi_fee_bps = round(0.07 * p_clamped * (1.0 - p_clamped) * 10000.0, 1)

    return {
        "mid_price_cents": mid_cents,
        "spread_bps": spread_bps,
        "obi_top5": obi_top5,
        "net_arb_cents": net_arb_cents,
        "vwap_divergence_cents": vwap_divergence_cents,
        "top5_liquidity_usd": top5_liquidity_usd,
        "wire_lag_ms": wire_lag_ms,
        "kalshi_fee_bps": kalshi_fee_bps,
    }
