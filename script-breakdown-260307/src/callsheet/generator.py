"""CallSheetGenerator — builds a CallSheet from a ShootingDay and scene data."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .models import CallSheet, CastCall, SceneCallInfo

if TYPE_CHECKING:
    from ..schedule.models import ActorSchedule, ProductionSchedule, ShootingDay
    from ..scene.models import Scene


def _add_minutes(hhmm: str, minutes: int) -> str:
    """Return a new HH:MM string offset by *minutes* from *hhmm*."""
    try:
        dt = datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)
        return dt.strftime("%H:%M")
    except ValueError:
        return hhmm


class CallSheetGenerator:
    """Generate a CallSheet for a single shooting day."""

    def generate(
        self,
        shooting_day: "ShootingDay",
        scenes: list["Scene"],
        entities: dict[int, dict],
        actors: list["ActorSchedule"],
        schedule: "ProductionSchedule",
        project_name: str = "",
    ) -> CallSheet:
        """Build a CallSheet from the provided data.

        Args:
            shooting_day:  The ShootingDay to generate the callsheet for.
            scenes:        All scenes in the production (globally numbered).
            entities:      Mapping of scene_number → entity dict
                           {"characters": [...], "props": [...]}.
            actors:        ActorSchedule list with character→actor name mapping.
            schedule:      Full ProductionSchedule (used for next-day preview).
            project_name:  Optional project name for the header.

        Returns:
            A populated CallSheet instance.
        """
        scene_map = {s.scene_number: s for s in scenes}
        actor_map = {a.character_name: a for a in actors}

        # ── Build SceneCallInfo list ───────────────────────────────
        scene_calls: list[SceneCallInfo] = []
        for snum in sorted(shooting_day.scene_ids):
            scene = scene_map.get(snum)
            if scene is None:
                continue
            ent = entities.get(snum, {})
            characters = ent.get("characters", [])
            props = ent.get("props", [])

            line_count = (scene.end_line - scene.start_line + 1) if scene.end_line > scene.start_line else 0
            pages = round(line_count / 55, 2)

            scene_calls.append(SceneCallInfo(
                scene_number=snum,
                heading=scene.heading,
                location=scene.location,
                int_ext=scene.int_ext,
                time_of_day=scene.time_of_day,
                pages=pages,
                cast_ids=list(characters),
                props=list(props),
            ))

        # ── Collect all unique characters across the day's scenes ──
        all_chars: dict[str, list[int]] = {}   # char_name → scene_numbers
        for sc in scene_calls:
            for char in sc.cast_ids:
                all_chars.setdefault(char, []).append(sc.scene_number)

        # Sort characters by the scene number they first appear in
        sorted_chars = sorted(all_chars.items(), key=lambda kv: kv[1][0])

        # ── Estimate call times ────────────────────────────────────
        # Characters are staggered in reverse order (first-appearing → earliest call).
        # Each actor needs ~30 min makeup; last actor arrives 30 min before crew call.
        # Maximum lead time is capped at 120 min so no actor is called before midnight.
        crew_call = shooting_day.call_time or "07:00"
        n = len(sorted_chars)
        MAX_LEAD_MIN = 120   # cap: never more than 2 hours before crew call
        cast_calls: list[CastCall] = []
        for idx, (char_name, scene_nums) in enumerate(sorted_chars):
            # reverse index: character appearing first gets the most lead time
            reverse_idx = n - 1 - idx
            raw_offset = (reverse_idx + 1) * 30   # minutes before crew_call
            offset_min = min(raw_offset, MAX_LEAD_MIN)
            call_t = _add_minutes(crew_call, -offset_min)
            on_set_t = crew_call                   # all actors ready by crew call

            actor_info = actor_map.get(char_name)
            actor_name = actor_info.actor_name if actor_info else ""

            cast_calls.append(CastCall(
                character_name=char_name,
                actor_name=actor_name,
                call_time=call_t,
                makeup_time=call_t,
                on_set_time=on_set_t,
                scenes=scene_nums,
            ))

        # ── Next-day preview ───────────────────────────────────────
        next_day_preview = ""
        if schedule and schedule.shooting_days:
            sorted_days = sorted(schedule.shooting_days, key=lambda d: d.date)
            current_dates = [d.date for d in sorted_days]
            try:
                cur_idx = current_dates.index(shooting_day.date)
                if cur_idx + 1 < len(sorted_days):
                    nd = sorted_days[cur_idx + 1]
                    nd_scene_ids = sorted(nd.scene_ids)
                    nd_scenes_text = "、".join(f"第{s}场" for s in nd_scene_ids[:5])
                    if len(nd_scene_ids) > 5:
                        nd_scenes_text += f"等共{len(nd_scene_ids)}场"
                    next_day_preview = (
                        f"{nd.date}（第{nd.day_number}拍摄日）"
                        f"  集合时间 {nd.call_time}"
                        f"  地点：{nd.location or '待定'}"
                        f"  {nd_scenes_text}"
                    )
            except ValueError:
                pass

        # ── Resolve location address from schedule.locations ───────
        location_address = ""
        if schedule:
            for loc_info in schedule.locations:
                if loc_info.name == shooting_day.location:
                    location_address = loc_info.address
                    break

        return CallSheet(
            date=shooting_day.date,
            day_number=shooting_day.day_number,
            crew_call=crew_call,
            location=shooting_day.location,
            location_address=location_address,
            scenes=scene_calls,
            cast=cast_calls,
            general_notes=shooting_day.notes,
            next_day_preview=next_day_preview,
            project_name=project_name,
        )
