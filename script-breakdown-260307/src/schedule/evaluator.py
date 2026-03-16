"""Objective-function evaluator for the scheduling module (排期目标函数).

目标函数：min Z = α·转场 + β·演员 + γ·场地 + δ·均衡度 + ε·总天数
所有子维度越低越好。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constraints import ConstraintChecker
from .models import ProductionSchedule, ScheduleConfig


# ---------------------------------------------------------------------------
# EvalResult — 评估结果
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    total: float        # 加权总分（越低越好）
    transition: float   # 转场成本（α 项）
    actor: float        # 演员成本（β 项，元）
    location: float     # 场地成本（γ 项，元）
    balance: float      # 均衡度（δ 项，每日场次数的方差）
    days: float         # 总拍摄天数（ε 项）

    def to_dict(self) -> dict[str, float]:
        return {
            "total": self.total,
            "transition": self.transition,
            "actor": self.actor,
            "location": self.location,
            "balance": self.balance,
            "days": self.days,
        }


# ---------------------------------------------------------------------------
# ScheduleEvaluator
# ---------------------------------------------------------------------------

class ScheduleEvaluator:
    """计算排期的目标函数值（越低越好）。

    Parameters
    ----------
    scenes:   list[Scene]         剧本场次列表
    entities: dict[int, dict]     scene_number -> {"characters": [...], "props": [...]}
    config:   ScheduleConfig      全局排期配置（权重在 schedule.config 中，此处仅备用）
    """

    # 硬约束违反惩罚系数（每条 error 级违反对应的分值加成）
    VIOLATION_PENALTY_ERROR   = 5000.0
    VIOLATION_PENALTY_WARNING =  500.0

    def __init__(
        self,
        scenes: list[Any],
        entities: dict[int, dict],
        config: ScheduleConfig,
        actors: list[Any] | None = None,
        locations: list[Any] | None = None,
    ) -> None:
        self._scene_map: dict[int, Any] = {s.scene_number: s for s in scenes}
        self._entities = entities
        self._default_config = config
        # ConstraintChecker 用于在目标函数中加入硬约束惩罚项
        self._checker = ConstraintChecker(
            scenes, entities,
            actors   or [],
            locations or [],
        )

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    def evaluate(self, schedule: ProductionSchedule) -> EvalResult:
        """计算整份排期的目标函数，返回各维度得分及加权总分。"""
        c_transition = self._cost_transition(schedule)
        c_actor      = self._cost_actor(schedule)
        c_location   = self._cost_location(schedule)
        c_balance    = self._cost_balance(schedule)
        c_days       = self._cost_days(schedule)

        # 硬约束惩罚项：错误级违反加大罚分，使 SA 拒绝产生约束违反的移动
        violations = self._checker.check_all(schedule)
        penalty = sum(
            self.VIOLATION_PENALTY_ERROR   if v.severity == "error"   else
            self.VIOLATION_PENALTY_WARNING
            for v in violations
        )

        cfg = schedule.config
        total = (
            cfg.weight_transition * c_transition
            + cfg.weight_actor    * c_actor
            + cfg.weight_location * c_location
            + cfg.weight_balance  * c_balance
            + cfg.weight_days     * c_days
            + penalty
        )
        return EvalResult(
            total=total,
            transition=c_transition,
            actor=c_actor,
            location=c_location,
            balance=c_balance,
            days=c_days,
        )

    # ── 各维度成本计算 ────────────────────────────────────────────────────────

    def _cost_transition(self, schedule: ProductionSchedule) -> float:
        """转场成本：相邻拍摄日地点发生变化的次数。

        地点不变（连续在同一外景）= 0；每次地点切换 +1。
        """
        days = schedule.shooting_days
        if len(days) <= 1:
            return 0.0
        changes = sum(
            1 for i in range(1, len(days))
            if days[i].location != days[i - 1].location
        )
        return float(changes)

    def _cost_actor(self, schedule: ProductionSchedule) -> float:
        """演员成本：每位演员的实际出工天数 × 日薪之和（元）。

        仅计算在 schedule.actors 中声明了 daily_rate 的演员。
        """
        # 统计每个角色的出工天数
        char_days: dict[str, int] = {}
        for day in schedule.shooting_days:
            appeared_today: set[str] = set()
            for sid in day.scene_ids:
                appeared_today.update(
                    self._entities.get(sid, {}).get("characters", [])
                )
            for char in appeared_today:
                char_days[char] = char_days.get(char, 0) + 1

        total = 0.0
        for actor in schedule.actors:
            days_worked = char_days.get(actor.character_name, 0)
            total += days_worked * actor.daily_rate
        return total

    def _cost_location(self, schedule: ProductionSchedule) -> float:
        """场地成本：从首次到末次使用该场地的跨度天数 × 日租之和（元）。

        跨度内哪怕有空档也计费，符合实际场地租用惯例。
        """
        loc_map = {loc.name: loc for loc in schedule.locations}

        # 记录每个场地的首个 / 末个 day_number
        loc_first: dict[str, int] = {}
        loc_last: dict[str, int] = {}
        for day in schedule.shooting_days:
            loc = day.location
            if loc not in loc_first:
                loc_first[loc] = day.day_number
            loc_last[loc] = day.day_number

        total = 0.0
        for loc_name, first in loc_first.items():
            span = loc_last[loc_name] - first + 1
            loc_info = loc_map.get(loc_name)
            cost_per_day = loc_info.cost_per_day if loc_info else 0.0
            total += span * cost_per_day
        return total

    def _cost_balance(self, schedule: ProductionSchedule) -> float:
        """均衡度：各拍摄日场次数的方差（值越大越不均衡）。"""
        days = schedule.shooting_days
        if not days:
            return 0.0
        counts = [len(d.scene_ids) for d in days]
        mean = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        return variance

    def _cost_days(self, schedule: ProductionSchedule) -> float:
        """总拍摄天数（拍摄日数量）。"""
        return float(len(schedule.shooting_days))
