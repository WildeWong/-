"""Hard-constraint checker for the scheduling module (排期约束检查)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .models import ProductionSchedule, ScheduleConfig, ShootingDay

if TYPE_CHECKING:
    from src.scene.models import Scene

# ── 中文星期 / 英文星期 → weekday() 映射 (0=Monday … 6=Sunday) ──────────────
_WEEKDAY_MAP: dict[str, int] = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6,
}

# 每场次估算拍摄时长（分钟）
_MINUTES_PER_SCENE = 45


# ---------------------------------------------------------------------------
# Violation — 违约记录
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    type: str                          # 约束类型标识，如 "actor_conflict"
    severity: str                      # "error" | "warning"
    message: str                       # 人类可读的说明
    day_date: str                      # 涉及的拍摄日期 "YYYY-MM-DD"
    scene_ids: list[int] = field(default_factory=list)  # 涉及的场次号


# ---------------------------------------------------------------------------
# ConstraintChecker
# ---------------------------------------------------------------------------

class ConstraintChecker:
    """检查排期是否满足所有硬约束，返回 Violation 列表。"""

    def __init__(
        self,
        scenes: list[Any],            # list[Scene]
        entities: dict[int, dict],    # scene_number -> {"characters": [...], "props": [...]}
        actors: list[Any],            # list[ActorSchedule]
        locations: list[Any],         # list[LocationInfo]
    ) -> None:
        # 以 scene_number 为键索引场次
        self._scene_map: dict[int, Any] = {s.scene_number: s for s in scenes}
        self._entities = entities
        # 以角色名为键索引演员档期
        self._actor_map: dict[str, Any] = {a.character_name: a for a in actors}
        # 以场地名为键索引场地信息
        self._location_map: dict[str, Any] = {loc.name: loc for loc in locations}
        # check_all 期间暂存当前排期，供子检查方法访问
        self._schedule: ProductionSchedule | None = None

    # ── 公开接口 ─────────────────────────────────────────────────────────────

    def check_all(self, schedule: ProductionSchedule) -> list[Violation]:
        """对整份排期执行全部约束检查，返回所有 Violation。"""
        self._schedule = schedule
        violations: list[Violation] = []
        for day in schedule.shooting_days:
            violations.extend(self.check_actor_conflict(day))
            violations.extend(self.check_actor_availability(day))
            violations.extend(self.check_location_availability(day))
            violations.extend(self.check_daily_hours(day))
            violations.extend(self.check_rest_days(day, schedule.config))
        self._schedule = None
        return violations

    def check_actor_conflict(self, day: ShootingDay) -> list[Violation]:
        """同一天同一演员出现在不同地点（场次的拍摄地点不一致时判定）。"""
        # 按场次所属地点分组，收集每个地点需要的演员
        loc_chars: dict[str, set[str]] = {}
        for sid in day.scene_ids:
            scene = self._scene_map.get(sid)
            loc = (scene.location if scene and scene.location else day.location)
            chars = set(self._entities.get(sid, {}).get("characters", []))
            loc_chars.setdefault(loc, set()).update(chars)

        if len(loc_chars) <= 1:
            return []

        # 找出在多个地点出现的演员
        char_locs: dict[str, list[str]] = {}
        for loc, chars in loc_chars.items():
            for char in chars:
                char_locs.setdefault(char, []).append(loc)

        violations: list[Violation] = []
        for char, locs in char_locs.items():
            unique_locs = list(dict.fromkeys(locs))  # 保序去重
            if len(unique_locs) > 1:
                violations.append(Violation(
                    type="actor_conflict",
                    severity="error",
                    message=(
                        f"演员「{char}」在 {day.date} 同天需出现在不同地点："
                        f"{' / '.join(unique_locs)}"
                    ),
                    day_date=day.date,
                    scene_ids=list(day.scene_ids),
                ))
        return violations

    def check_actor_availability(self, day: ShootingDay) -> list[Violation]:
        """演员在不可用日期被安排拍摄。"""
        # 收集当天所有场次需要的演员
        needed: set[str] = set()
        for sid in day.scene_ids:
            needed.update(self._entities.get(sid, {}).get("characters", []))

        violations: list[Violation] = []
        for char in needed:
            actor = self._actor_map.get(char)
            if actor is None:
                continue

            # 明确标记不可用
            if day.date in actor.unavailable_dates:
                label = f"「{actor.actor_name}」" if actor.actor_name else ""
                violations.append(Violation(
                    type="actor_unavailable",
                    severity="error",
                    message=f"演员{label}（角色「{char}」）在 {day.date} 标记为不可用",
                    day_date=day.date,
                    scene_ids=self._scenes_with_char(day.scene_ids, char),
                ))
            # available_dates 非空且不含该日期（警告）
            elif actor.available_dates and day.date not in actor.available_dates:
                label = f"「{actor.actor_name}」" if actor.actor_name else ""
                violations.append(Violation(
                    type="actor_unavailable",
                    severity="warning",
                    message=f"演员{label}（角色「{char}」）的档期列表不含 {day.date}",
                    day_date=day.date,
                    scene_ids=self._scenes_with_char(day.scene_ids, char),
                ))
        return violations

    def check_location_availability(self, day: ShootingDay) -> list[Violation]:
        """场地在不可用日期被使用。"""
        loc_info = self._location_map.get(day.location)
        if loc_info is None or not loc_info.available_dates:
            return []

        if day.date not in loc_info.available_dates:
            return [Violation(
                type="location_unavailable",
                severity="error",
                message=f"场地「{day.location}」在 {day.date} 不在可用日期列表中",
                day_date=day.date,
                scene_ids=list(day.scene_ids),
            )]
        return []

    def check_daily_hours(self, day: ShootingDay) -> list[Violation]:
        """每天预估工时超过配置上限（每场约 45 分钟）。"""
        max_hours = (
            self._schedule.config.max_hours_per_day
            if self._schedule else 12.0
        )
        estimated = len(day.scene_ids) * _MINUTES_PER_SCENE / 60
        if estimated > max_hours:
            return [Violation(
                type="daily_hours_exceeded",
                severity="error",
                message=(
                    f"{day.date} 预估工时 {estimated:.1f}h 超过上限 {max_hours}h"
                    f"（{len(day.scene_ids)} 场 × {_MINUTES_PER_SCENE}min）"
                ),
                day_date=day.date,
                scene_ids=list(day.scene_ids),
            )]
        return []

    def check_rest_days(self, day: ShootingDay, config: ScheduleConfig) -> list[Violation]:
        """休息日不应排戏（支持具体日期和星期几两种格式）。"""
        if not config.rest_days:
            return []

        # 精确日期匹配
        if day.date in config.rest_days:
            return [Violation(
                type="rest_day_violation",
                severity="error",
                message=f"{day.date} 是指定休息日，不应安排拍摄",
                day_date=day.date,
                scene_ids=list(day.scene_ids),
            )]

        # 星期几匹配
        try:
            weekday = datetime.strptime(day.date, "%Y-%m-%d").weekday()
            for rest in config.rest_days:
                if _WEEKDAY_MAP.get(rest) == weekday:
                    return [Violation(
                        type="rest_day_violation",
                        severity="error",
                        message=f"{day.date}（{rest}）是指定休息日，不应安排拍摄",
                        day_date=day.date,
                        scene_ids=list(day.scene_ids),
                    )]
        except ValueError:
            pass

        return []

    def can_add_scene(self, day: ShootingDay, scene_id: int) -> tuple[bool, str]:
        """判断能否向某天添加一个场次。返回 (可行, 原因说明)。"""
        config = self._schedule.config if self._schedule else None
        max_hours = config.max_hours_per_day if config else 12.0

        # ① 工时检查
        new_hours = (len(day.scene_ids) + 1) * _MINUTES_PER_SCENE / 60
        if new_hours > max_hours:
            return False, (
                f"添加后预估工时 {new_hours:.1f}h 将超过上限 {max_hours}h"
            )

        # ② 演员档期检查
        new_chars = set(self._entities.get(scene_id, {}).get("characters", []))
        for char in new_chars:
            actor = self._actor_map.get(char)
            if actor is None:
                continue
            label = actor.actor_name or char
            if day.date in actor.unavailable_dates:
                return False, f"演员「{label}」在 {day.date} 不可用"
            if actor.available_dates and day.date not in actor.available_dates:
                return False, f"演员「{label}」的档期不含 {day.date}"

        # ③ 地点冲突检查
        scene = self._scene_map.get(scene_id)
        if scene and scene.location and scene.location != day.location:
            existing_chars: set[str] = set()
            for sid in day.scene_ids:
                existing_chars.update(self._entities.get(sid, {}).get("characters", []))
            shared = new_chars & existing_chars
            if shared:
                return False, (
                    f"场次 {scene_id} 地点「{scene.location}」与当天主场地"
                    f"「{day.location}」不同，且演员 {', '.join(sorted(shared))} 已被安排"
                )

        return True, ""

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    def _scenes_with_char(self, scene_ids: list[int], char: str) -> list[int]:
        """从 scene_ids 中筛选出包含指定角色的场次号。"""
        return [
            sid for sid in scene_ids
            if char in self._entities.get(sid, {}).get("characters", [])
        ]
