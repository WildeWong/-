"""Data models for the callsheet module (通告单)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CastCall:
    """Per-actor call information for a single shooting day."""

    character_name: str
    actor_name: str = ""
    call_time: str = ""       # HH:MM  演员到组时间
    makeup_time: str = ""     # HH:MM  化妆开始时间（= call_time）
    on_set_time: str = ""     # HH:MM  妆造完毕、进场候机时间
    scenes: list[int] = field(default_factory=list)   # 当日出现的 scene_number 列表
    wardrobe_notes: str = ""  # 服装造型备注
    status: str = "W"         # W = working / S = standby

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_name": self.character_name,
            "actor_name": self.actor_name,
            "call_time": self.call_time,
            "makeup_time": self.makeup_time,
            "on_set_time": self.on_set_time,
            "scenes": self.scenes,
            "wardrobe_notes": self.wardrobe_notes,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CastCall:
        return cls(
            character_name=data.get("character_name", ""),
            actor_name=data.get("actor_name", ""),
            call_time=data.get("call_time", ""),
            makeup_time=data.get("makeup_time", ""),
            on_set_time=data.get("on_set_time", ""),
            scenes=data.get("scenes", []),
            wardrobe_notes=data.get("wardrobe_notes", ""),
            status=data.get("status", "W"),
        )


@dataclass
class SceneCallInfo:
    """Scene entry as printed in the callsheet."""

    scene_number: int
    heading: str = ""
    location: str = ""
    int_ext: str = ""       # INT / EXT
    time_of_day: str = ""   # DAY / NIGHT / DAWN / DUSK
    pages: float = 0.0      # 页数估算（line_count / 55）
    cast_ids: list[str] = field(default_factory=list)   # character names for this scene
    props: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_number": self.scene_number,
            "heading": self.heading,
            "location": self.location,
            "int_ext": self.int_ext,
            "time_of_day": self.time_of_day,
            "pages": self.pages,
            "cast_ids": self.cast_ids,
            "props": self.props,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SceneCallInfo:
        return cls(
            scene_number=data.get("scene_number", 0),
            heading=data.get("heading", ""),
            location=data.get("location", ""),
            int_ext=data.get("int_ext", ""),
            time_of_day=data.get("time_of_day", ""),
            pages=data.get("pages", 0.0),
            cast_ids=data.get("cast_ids", []),
            props=data.get("props", []),
            notes=data.get("notes", ""),
        )


@dataclass
class CallSheet:
    """Daily production callsheet (每日通告单)."""

    date: str                    # "YYYY-MM-DD"
    day_number: int = 0          # 第几个拍摄日（从 1 起）
    crew_call: str = "07:00"     # 全体集合时间
    location: str = ""           # 主要拍摄地点名称
    location_address: str = ""   # 具体地址
    scenes: list[SceneCallInfo] = field(default_factory=list)
    cast: list[CastCall] = field(default_factory=list)
    general_notes: str = ""      # 整体注意事项
    next_day_preview: str = ""   # 明日预告
    producer: str = ""
    director: str = ""
    project_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "day_number": self.day_number,
            "crew_call": self.crew_call,
            "location": self.location,
            "location_address": self.location_address,
            "scenes": [s.to_dict() for s in self.scenes],
            "cast": [c.to_dict() for c in self.cast],
            "general_notes": self.general_notes,
            "next_day_preview": self.next_day_preview,
            "producer": self.producer,
            "director": self.director,
            "project_name": self.project_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallSheet:
        return cls(
            date=data.get("date", ""),
            day_number=data.get("day_number", 0),
            crew_call=data.get("crew_call", "07:00"),
            location=data.get("location", ""),
            location_address=data.get("location_address", ""),
            scenes=[SceneCallInfo.from_dict(s) for s in data.get("scenes", [])],
            cast=[CastCall.from_dict(c) for c in data.get("cast", [])],
            general_notes=data.get("general_notes", ""),
            next_day_preview=data.get("next_day_preview", ""),
            producer=data.get("producer", ""),
            director=data.get("director", ""),
            project_name=data.get("project_name", ""),
        )
