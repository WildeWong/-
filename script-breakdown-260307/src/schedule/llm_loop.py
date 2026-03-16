"""CP-SAT + LLM closed-loop schedule refinement engine.

Flow (up to *max_rounds* iterations):
  1. CP-SAT produces a mathematically optimal schedule.
  2. LLM reviews it from a producer's perspective and returns structured
     feedback (issues + optional CP-SAT-compatible constraints).
  3. New constraints are injected into the next solve call.
  4. Repeat until the LLM is satisfied or the round budget is exhausted.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .models import ProductionSchedule
from .optimizer import ScheduleOptimizer

logger = logging.getLogger(__name__)

# System prompt handed to the LLM at the start of each review call
_SYSTEM_PROMPT = (
    "你是经验丰富的影视制片人，精通中国影视制作流程。"
    "请务必返回严格符合要求的 JSON，不要添加任何多余的文字或 Markdown 标记。"
)

# User prompt template — {schedule_summary} will be substituted at runtime
_REVIEW_PROMPT_TEMPLATE = """\
你是经验丰富的影视制片人。以下是算法生成的拍摄排期。
请从实际拍摄角度审查，找出"数学上合理但实际拍摄中有问题"的安排。

排期数据：
{schedule_summary}

请严格按以下 JSON 格式返回你的审查意见（返回纯 JSON，不要其他文字）：
{{
  "approved": true,
  "issues": [
    {{
      "type": "scene_order | actor_fatigue | location_logic | time_conflict | weather_risk | emotional_flow",
      "description": "具体问题描述",
      "affected_scenes": [],
      "suggestion": "具体的修改建议",
      "constraint": {{
        "type": "must_before | must_same_day | must_different_day | must_not_date | prefer_consecutive",
        "scenes": [],
        "params": {{}}
      }}
    }}
  ]
}}

说明：
- approved: 如果排期已经足够好，设为 true 并让 issues 为空数组
- constraint 字段是可选的；如果问题无法用结构化约束表达，可省略
- must_before: scenes 中第一个场次必须排在第二个之前
- must_same_day: 所有 scenes 必须在同一天拍摄
- must_different_day: 所有 scenes 不能在同一天拍摄
- must_not_date: 指定场次不能在 params.date 日期拍摄
- prefer_consecutive: 这些场次尽量安排在连续的天内（软约束）\
"""


class LLMScheduleLoop:
    """CP-SAT + LLM closed-loop refinement engine."""

    def __init__(
        self,
        optimizer: ScheduleOptimizer,
        llm: Any,          # BaseLLM — imported lazily to avoid circular deps
        max_rounds: int = 3,
    ) -> None:
        self.optimizer    = optimizer
        self.llm          = llm
        self.max_rounds   = max_rounds
        # Full record of every iteration: list of round-result dicts
        self.history: list[dict] = []

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        time_limit_per_round: float = 15,
        initial_constraints: list[dict] | None = None,
    ) -> dict:
        """
        Execute the CP-SAT → LLM → re-solve feedback loop.

        Parameters
        ----------
        time_limit_per_round : seconds per CP-SAT round
        initial_constraints  : pre-seeded constraints (e.g. from the preference
                               learner) that are active from round 1 onwards

        Returns
        -------
        {
            "schedule"    : ProductionSchedule,
            "rounds"      : [ {round, solver_status, llm_suggestions, accepted}, ... ],
            "total_rounds": int,
            "final_score" : float,
        }
        """
        # Accumulate all LLM-derived extra constraints across rounds;
        # seed with any pre-learned constraints so they are applied from round 1.
        accumulated_constraints: list[dict] = list(initial_constraints or [])
        schedule: ProductionSchedule | None = None

        for round_num in range(1, self.max_rounds + 1):
            # ── Step 1: CP-SAT solve ─────────────────────────────────────────
            try:
                schedule = self.optimizer.solve(
                    time_limit_seconds=time_limit_per_round,
                    extra_constraints=accumulated_constraints if accumulated_constraints else None,
                )
                solver_status = "feasible"
            except RuntimeError as exc:
                logger.warning("Round %d: solver failed — %s", round_num, exc)
                # Record failure and stop; return best schedule found so far
                self.history.append({
                    "round": round_num,
                    "solver_status": "infeasible",
                    "llm_suggestions": [],
                    "accepted": [],
                    "error": str(exc),
                })
                break

            # ── Step 2: LLM review ───────────────────────────────────────────
            summary = self._schedule_to_summary(schedule)
            prompt  = _REVIEW_PROMPT_TEMPLATE.format(schedule_summary=summary)

            try:
                raw_response = self.llm.complete(prompt, _SYSTEM_PROMPT)
                parsed       = self._parse_llm_response(raw_response)
            except Exception as exc:
                logger.warning("Round %d: LLM call failed — %s", round_num, exc)
                parsed = {"approved": True, "issues": []}

            issues       = parsed.get("issues") or []
            approved     = parsed.get("approved", True) or not issues
            suggestions  = [iss.get("description", "") for iss in issues]

            # ── Step 3: Convert issues to constraints ─────────────────────────
            new_constraints: list[dict] = []
            for issue in issues:
                c = self._issue_to_constraint(issue)
                if c:
                    new_constraints.append(c)

            # Record this round
            round_record: dict = {
                "round":            round_num,
                "solver_status":    solver_status,
                "llm_suggestions":  suggestions,
                "accepted":         [c["type"] for c in new_constraints],
                "issues_raw":       issues,
            }
            self.history.append(round_record)

            # ── Step 4: Decide whether to continue ────────────────────────────
            if approved or not new_constraints:
                # LLM is satisfied (or gave no actionable constraints) → stop
                break

            accumulated_constraints.extend(new_constraints)
            logger.info(
                "Round %d: %d new constraint(s) added, continuing…",
                round_num, len(new_constraints),
            )

        # If no schedule was produced at all (impossible in practice), fallback
        if schedule is None:
            schedule = self.optimizer.solve(time_limit_seconds=time_limit_per_round)

        final_score = self._compute_score(schedule)

        return {
            "schedule":     schedule,
            "rounds":       self.history,
            "total_rounds": len(self.history),
            "final_score":  final_score,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _schedule_to_summary(self, schedule: ProductionSchedule) -> str:
        """Convert a ProductionSchedule to a compact human-readable text for the LLM."""
        lines: list[str] = [
            f"共 {len(schedule.shooting_days)} 个拍摄日，"
            f"开机 {schedule.start_date}，预计杀青 {schedule.end_date}。",
            "",
        ]
        for day in schedule.shooting_days:
            scene_ids_str = ", ".join(str(s) for s in day.scene_ids)
            lines.append(
                f"第{day.day_number}天 ({day.date})  地点: {day.location}  "
                f"场次: [{scene_ids_str}]"
            )
            for sid in day.scene_ids:
                chars = self.optimizer._scene_chars.get(sid, set())
                loc   = self.optimizer._scene_loc.get(sid, "")
                chars_str = "、".join(sorted(chars)) if chars else "无角色信息"
                lines.append(f"    场次{sid}: {loc} | 角色: {chars_str}")
        return "\n".join(lines)

    def _parse_llm_response(self, response_text: str) -> dict:
        """
        Extract the JSON payload from an LLM response.

        Handles markdown code-fence wrapping (```json … ```) and any leading/
        trailing whitespace.  Falls back to {"approved": True, "issues": []} on
        any parse error so the loop can continue gracefully.
        """
        text = response_text.strip()

        # Strip markdown code fence if present
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            # Remove closing fence
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()

        # Some models prepend "json" after stripping the fence
        if text.startswith("json"):
            text = text[4:].lstrip()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.debug("Failed to parse LLM JSON response: %r", text[:200])

        return {"approved": True, "issues": []}

    def _issue_to_constraint(self, issue: dict) -> dict | None:
        """
        Convert one LLM issue dict to an extra_constraint dict accepted by
        ScheduleOptimizer.solve(extra_constraints=…).

        Returns None if the issue carries no actionable constraint.
        """
        constraint = issue.get("constraint")
        if not isinstance(constraint, dict):
            return None

        ctype  = constraint.get("type", "")
        scenes = constraint.get("scenes", [])
        params = constraint.get("params") or {}

        valid_types = {
            "must_before",
            "must_same_day",
            "must_different_day",
            "must_not_date",
            "prefer_consecutive",
        }
        if ctype not in valid_types:
            return None

        # Require at least one scene reference (two for ordering constraints)
        if not scenes:
            return None
        if ctype == "must_before" and len(scenes) < 2:
            return None
        if ctype == "must_not_date" and not params.get("date"):
            return None

        # Normalise scene IDs to plain ints
        try:
            scene_ids = [int(s) for s in scenes]
        except (TypeError, ValueError):
            return None

        return {
            "type":   ctype,
            "scenes": scene_ids,
            "params": params,
        }

    def _compute_score(self, schedule: ProductionSchedule) -> float:
        """
        Simple weighted score matching the CP-SAT objective structure:
        score = days × weight_days + location_changes × weight_transition

        Lower is better.
        """
        cfg   = self.optimizer.config
        days  = schedule.shooting_days
        n_days = len(days)

        # Count consecutive-day location changes
        changes = sum(
            1
            for i in range(len(days) - 1)
            if days[i].location != days[i + 1].location
        )

        return round(
            n_days  * cfg.weight_days       +
            changes * cfg.weight_transition,
            2,
        )
