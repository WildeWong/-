"""Data models for the scheduling module (排期管理)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# ShootingDay — 一个拍摄日
# ---------------------------------------------------------------------------

@dataclass
class ShootingDay:
    date: str                          # "YYYY-MM-DD"
    day_number: int                    # 第几个拍摄日（从 1 开始）
    scene_ids: list[int] = field(default_factory=list)
    location: str = ""
    call_time: str = "07:00"
    estimated_end: str = "19:00"
    notes: str = ""
    status: str = "planned"            # planned / shooting / completed / cancelled
    weather_backup: str = ""           # 备用场地或天气预案

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "day_number": self.day_number,
            "scene_ids": self.scene_ids,
            "location": self.location,
            "call_time": self.call_time,
            "estimated_end": self.estimated_end,
            "notes": self.notes,
            "status": self.status,
            "weather_backup": self.weather_backup,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShootingDay:
        return cls(
            date=data.get("date", ""),
            day_number=data.get("day_number", 0),
            scene_ids=data.get("scene_ids", []),
            location=data.get("location", ""),
            call_time=data.get("call_time", "07:00"),
            estimated_end=data.get("estimated_end", "19:00"),
            notes=data.get("notes", ""),
            status=data.get("status", "planned"),
            weather_backup=data.get("weather_backup", ""),
        )


# ---------------------------------------------------------------------------
# ActorSchedule — 演员档期
# ---------------------------------------------------------------------------

@dataclass
class ActorSchedule:
    character_name: str                # 角色名（与剧本实体对应）
    actor_name: str = ""               # 实际演员姓名
    available_dates: list[str] = field(default_factory=list)    # 可拍日期
    unavailable_dates: list[str] = field(default_factory=list)  # 不可拍日期
    daily_rate: float = 0.0            # 日薪（元）
    contact: str = ""                  # 联系方式

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_name": self.character_name,
            "actor_name": self.actor_name,
            "available_dates": self.available_dates,
            "unavailable_dates": self.unavailable_dates,
            "daily_rate": self.daily_rate,
            "contact": self.contact,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActorSchedule:
        return cls(
            character_name=data.get("character_name", ""),
            actor_name=data.get("actor_name", ""),
            available_dates=data.get("available_dates", []),
            unavailable_dates=data.get("unavailable_dates", []),
            daily_rate=data.get("daily_rate", 0.0),
            contact=data.get("contact", ""),
        )


# ---------------------------------------------------------------------------
# LocationInfo — 场地信息
# ---------------------------------------------------------------------------

@dataclass
class LocationInfo:
    name: str                          # 场地名称（与剧本地点对应）
    address: str = ""
    contact: str = ""
    available_dates: list[str] = field(default_factory=list)
    cost_per_day: float = 0.0          # 每日场地费（元）
    notes: str = ""
    travel_time_minutes: int = 0       # 到达片场所需时间（分钟）

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "address": self.address,
            "contact": self.contact,
            "available_dates": self.available_dates,
            "cost_per_day": self.cost_per_day,
            "notes": self.notes,
            "travel_time_minutes": self.travel_time_minutes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocationInfo:
        return cls(
            name=data.get("name", ""),
            address=data.get("address", ""),
            contact=data.get("contact", ""),
            available_dates=data.get("available_dates", []),
            cost_per_day=data.get("cost_per_day", 0.0),
            notes=data.get("notes", ""),
            travel_time_minutes=data.get("travel_time_minutes", 0),
        )


# ---------------------------------------------------------------------------
# ScheduleConfig — 排期配置（权重 & 约束）
# ---------------------------------------------------------------------------

@dataclass
class ScheduleConfig:
    start_date: str                    # 开机日期 "YYYY-MM-DD"
    max_hours_per_day: float = 12.0    # 每日最长工时
    rest_days: list[str] = field(default_factory=list)  # 固定休息日（周几或具体日期）
    # 目标函数权重
    weight_transition: float = 1.0    # α 转场成本
    weight_actor: float = 1.0         # β 演员成本
    weight_location: float = 1.0      # γ 场地成本
    weight_balance: float = 0.5       # δ 均衡度
    weight_days: float = 1.5          # ε 总天数
    # 求解器扩展字段
    scene_duration_map: dict = field(default_factory=dict)   # {scene_number: hours}
    genre_key: str = "B1_现代都市"         # 项目类型（表B的key），影响类型系数
    constraint_level: str = "relaxed"   # "strict" / "standard" / "relaxed"
    solver_time_limit: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "max_hours_per_day": self.max_hours_per_day,
            "rest_days": self.rest_days,
            "weight_transition": self.weight_transition,
            "weight_actor": self.weight_actor,
            "weight_location": self.weight_location,
            "weight_balance": self.weight_balance,
            "weight_days": self.weight_days,
            "scene_duration_map": self.scene_duration_map,
            "genre_key": self.genre_key,
            "constraint_level": self.constraint_level,
            "solver_time_limit": self.solver_time_limit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleConfig:
        return cls(
            start_date=data.get("start_date", ""),
            max_hours_per_day=data.get("max_hours_per_day", 12.0),
            rest_days=data.get("rest_days", []),
            weight_transition=data.get("weight_transition", 1.0),
            weight_actor=data.get("weight_actor", 1.0),
            weight_location=data.get("weight_location", 1.0),
            weight_balance=data.get("weight_balance", 0.5),
            weight_days=data.get("weight_days", 1.5),
            scene_duration_map=data.get("scene_duration_map", {}),
            genre_key=data.get("genre_key", "B1_现代都市"),
            constraint_level=data.get("constraint_level", "relaxed"),
            solver_time_limit=data.get("solver_time_limit", 30),
        )


# ---------------------------------------------------------------------------
# ProductionSchedule — 排期总表
# ---------------------------------------------------------------------------

@dataclass
class ProductionSchedule:
    shooting_days: list[ShootingDay] = field(default_factory=list)
    actors: list[ActorSchedule] = field(default_factory=list)
    locations: list[LocationInfo] = field(default_factory=list)
    config: ScheduleConfig = field(default_factory=lambda: ScheduleConfig(start_date=""))
    start_date: str = ""               # 实际开机日（冗余存储，方便快速读取）
    end_date: str = ""                 # 预计杀青日
    warnings: list = field(default_factory=list)   # 数据清洗 / 降级警告
    solver_status: str = "ok"          # "optimal" | "relaxed" | "fallback" | "emergency" | "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "shooting_days": [d.to_dict() for d in self.shooting_days],
            "actors": [a.to_dict() for a in self.actors],
            "locations": [l.to_dict() for l in self.locations],
            "config": self.config.to_dict(),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "warnings": list(self.warnings),
            "solver_status": self.solver_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductionSchedule:
        config_data = data.get("config", {})
        return cls(
            shooting_days=[ShootingDay.from_dict(d) for d in data.get("shooting_days", [])],
            actors=[ActorSchedule.from_dict(a) for a in data.get("actors", [])],
            locations=[LocationInfo.from_dict(l) for l in data.get("locations", [])],
            config=ScheduleConfig.from_dict(config_data) if config_data else ScheduleConfig(start_date=""),
            start_date=data.get("start_date", ""),
            end_date=data.get("end_date", ""),
            warnings=list(data.get("warnings", [])),
            solver_status=data.get("solver_status", "ok"),
        )


# ---------------------------------------------------------------------------
# ScheduleSnapshot — 排期快照（支持回滚 & diff）
# ---------------------------------------------------------------------------

@dataclass
class ScheduleSnapshot:
    version: int                       # 单调递增版本号
    timestamp: str                     # ISO 8601 时间戳
    trigger: str                       # 触发原因，如 "manual_adjust" / "optimizer_run"
    schedule_data: dict[str, Any] = field(default_factory=dict)  # ProductionSchedule.to_dict()
    diff_summary: str = ""             # 与上一版本的差异摘要

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "trigger": self.trigger,
            "schedule_data": self.schedule_data,
            "diff_summary": self.diff_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleSnapshot:
        return cls(
            version=data.get("version", 0),
            timestamp=data.get("timestamp", ""),
            trigger=data.get("trigger", ""),
            schedule_data=data.get("schedule_data", {}),
            diff_summary=data.get("diff_summary", ""),
        )
