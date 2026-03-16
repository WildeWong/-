"""Lightweight online preference learner for the scheduling module.

Learns user's implicit priorities by observing manual schedule adjustments:
  • Which cost dimensions the user tends to improve (→ raise that weight)
  • Structural rules confirmed through the LLM feedback loop (→ persist as extra_constraints)

Algorithm: Exponential Moving Average (EMA) — no neural networks, no heavy deps.

Storage: a single JSON file next to schedule.json in the project directory.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import ProductionSchedule, ScheduleConfig


# ── Constants ────────────────────────────────────────────────────────────────

_WEIGHT_KEYS = (
    "weight_transition",
    "weight_actor",
    "weight_location",
    "weight_balance",
    "weight_days",
)

_DEFAULT_WEIGHTS: dict[str, float] = {
    "weight_transition": 1.0,
    "weight_actor":      1.0,
    "weight_location":   1.0,
    "weight_balance":    0.5,
    "weight_days":       1.5,
}

# EvalResult attribute → weight key mapping
_EVAL_TO_WEIGHT: dict[str, str] = {
    "transition": "weight_transition",
    "actor":      "weight_actor",
    "location":   "weight_location",
    "balance":    "weight_balance",
    "days":       "weight_days",
}

_WEIGHT_MIN = 0.05
_WEIGHT_MAX = 5.0


# ── Main class ────────────────────────────────────────────────────────────────

class SchedulePreferenceLearner:
    """
    Lightweight preference learner for production scheduling.

    What is learned
    ---------------
    1. The relative importance of the five objective-function weights
       (transition, actor, location, balance, days).
    2. Structural rules (extra_constraints) confirmed by the user via the
       LLM feedback loop.

    Learning method
    ---------------
    Each manual adjustment is a training sample:
      (before_eval, after_eval)  →  which dimensions improved?

    A dimension that improved signals the user values it highly.
    EMA update: new_w = old_w + lr × (|delta_i| / max_|delta|)
    Weights are re-normalised after each update so their sum is stable.

    Storage
    -------
    JSON file at *save_path* (passed at construction time).
    Typically: <project_dir>/schedule_preferences.json
    """

    def __init__(self, save_path: str) -> None:
        self.save_path     = save_path
        self.learning_rate = 0.3          # EMA step size
        # Mutable learned state
        self.learned_weights: dict[str, float] = dict(_DEFAULT_WEIGHTS)
        self.learned_rules:   list[dict]        = []  # extra_constraints format
        self.adjustments:     list[dict]        = []  # training history
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Restore learned state from disk; silently ignore corrupt files."""
        if not os.path.exists(self.save_path):
            return
        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_w = data.get("weights", {})
            # Validate and merge — only update keys that exist in default weights
            for key in _WEIGHT_KEYS:
                val = loaded_w.get(key)
                if isinstance(val, (int, float)) and _WEIGHT_MIN <= val <= _WEIGHT_MAX:
                    self.learned_weights[key] = float(val)
            if isinstance(data.get("rules"), list):
                self.learned_rules = data["rules"]
            if isinstance(data.get("adjustments"), list):
                self.adjustments = data["adjustments"]
        except Exception:
            pass  # corrupt file — start fresh

    def _save(self) -> None:
        """Persist learned state to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(self.save_path)), exist_ok=True)
        payload = {
            "weights":     dict(self.learned_weights),
            "rules":       self.learned_rules,
            # Keep only the most recent 100 records to bound file size
            "adjustments": self.adjustments[-100:],
        }
        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ── Learning from manual adjustments ─────────────────────────────────────

    def record_adjustment(
        self,
        before_schedule: "ProductionSchedule",
        after_schedule:  "ProductionSchedule",
        evaluator:       Any,          # ScheduleEvaluator
    ) -> None:
        """
        Observe a manual schedule adjustment and update learned weights.

        Called *after* the user modifies the schedule (add/remove/move scenes).

        Algorithm
        ---------
        1. Evaluate both schedules with the raw component scores.
        2. For each dimension, compute delta = after_score − before_score.
           Negative delta ↔ user improved this dimension.
        3. Build a normalised improvement signal (in [0, 1]) for each dim.
        4. Increase the weights of improved dimensions (EMA step).
        5. Re-normalise so the weight sum stays close to the original.
        6. Persist.

        Parameters
        ----------
        before_schedule: schedule state before the user's change
        after_schedule:  schedule state after the user's change
        evaluator:       ScheduleEvaluator instance (already constructed)
        """
        try:
            before_eval = evaluator.evaluate(before_schedule)
            after_eval  = evaluator.evaluate(after_schedule)
        except Exception:
            return  # never crash on learning failures

        # Raw component deltas  (negative = dimension improved)
        deltas: dict[str, float] = {}
        for eval_key, weight_key in _EVAL_TO_WEIGHT.items():
            before_val = getattr(before_eval, eval_key, 0.0)
            after_val  = getattr(after_eval,  eval_key, 0.0)
            deltas[weight_key] = float(after_val - before_val)

        # Skip if nothing changed
        if all(math.isclose(d, 0.0, abs_tol=1e-9) for d in deltas.values()):
            return

        # Normalise by the largest absolute change so all signals are in [0, 1]
        max_abs = max(abs(d) for d in deltas.values())
        if max_abs == 0.0:
            return

        original_sum = sum(self.learned_weights.values())
        new_weights  = dict(self.learned_weights)

        for key, delta in deltas.items():
            if delta < 0:   # user improved this dimension → raise its weight
                signal = abs(delta) / max_abs   # [0, 1]
                new_weights[key] = min(
                    _WEIGHT_MAX,
                    new_weights[key] + self.learning_rate * signal,
                )

        # Re-normalise: keep the total weight sum roughly unchanged
        new_sum = sum(new_weights.values())
        if new_sum > 0 and original_sum > 0:
            scale = original_sum / new_sum
            for key in new_weights:
                new_weights[key] = round(
                    max(_WEIGHT_MIN, new_weights[key] * scale), 4
                )

        self.learned_weights = new_weights

        # Append a compact training record
        self.adjustments.append({
            "timestamp":     datetime.now().isoformat(timespec="seconds"),
            "deltas":        {k: round(v, 4) for k, v in deltas.items()},
            "weights_after": dict(new_weights),
        })
        self._save()

    # ── Learning from LLM feedback ────────────────────────────────────────────

    def record_rule_from_llm(self, rule: dict) -> None:
        """
        Persist a structural rule that the user confirmed through the LLM loop.

        rule format (passed from LLMScheduleLoop):
            {
              "type":   "must_before" | "must_same_day" | ... ,
              "scenes": [scene_number, ...],
              "reason": "human-readable explanation",   # optional
              "params": {},                             # optional
            }

        The rule is stored in the extra_constraints format so that
        get_extra_constraints() can return it directly.
        """
        normalised: dict = {
            "type":   rule.get("type", ""),
            "scenes": [int(s) for s in rule.get("scenes", [])],
            "params": rule.get("params") or {},
            "reason": rule.get("reason", ""),
        }
        # De-duplicate by (type, scenes)
        key = (normalised["type"], tuple(normalised["scenes"]))
        for existing in self.learned_rules:
            if (existing.get("type"), tuple(existing.get("scenes", []))) == key:
                return  # already recorded
        if normalised["type"] and normalised["scenes"]:
            self.learned_rules.append(normalised)
            self._save()

    # ── Providing suggestions ─────────────────────────────────────────────────

    def get_suggested_config(self, base_config: "ScheduleConfig") -> "ScheduleConfig":
        """
        Return a ScheduleConfig identical to *base_config* except that the
        five objective weights are replaced by the learned values.

        The caller should treat the result as a *suggestion* — the user can
        override any weight in the UI.
        """
        from .models import ScheduleConfig  # lazy import to avoid circularity
        w = self.learned_weights
        return ScheduleConfig(
            start_date=base_config.start_date,
            max_hours_per_day=base_config.max_hours_per_day,
            rest_days=list(base_config.rest_days),
            weight_transition=w.get("weight_transition", _DEFAULT_WEIGHTS["weight_transition"]),
            weight_actor     =w.get("weight_actor",      _DEFAULT_WEIGHTS["weight_actor"]),
            weight_location  =w.get("weight_location",   _DEFAULT_WEIGHTS["weight_location"]),
            weight_balance   =w.get("weight_balance",    _DEFAULT_WEIGHTS["weight_balance"]),
            weight_days      =w.get("weight_days",       _DEFAULT_WEIGHTS["weight_days"]),
        )

    def get_extra_constraints(self) -> list[dict]:
        """
        Return learned structural rules as CP-SAT extra_constraints dicts,
        ready to pass directly to ScheduleOptimizer.solve(extra_constraints=…).
        """
        return [
            {
                "type":   r["type"],
                "scenes": r["scenes"],
                "params": r.get("params") or {},
            }
            for r in self.learned_rules
            if r.get("type") and r.get("scenes")
        ]

    # ── Utilities ─────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all learned data and reset to factory defaults."""
        self.learned_weights = dict(_DEFAULT_WEIGHTS)
        self.learned_rules   = []
        self.adjustments     = []
        self._save()

    def to_dict(self) -> dict:
        """Serialise current learned state for the API response."""
        return {
            "weights":          dict(self.learned_weights),
            "rules":            list(self.learned_rules),
            "adjustment_count": len(self.adjustments),
            "last_adjusted":    (
                self.adjustments[-1]["timestamp"] if self.adjustments else None
            ),
        }
