"""Scheduling optimizer — Google OR-Tools CP-SAT constraint programming solver.

Replaces the previous greedy + simulated-annealing implementation with a
single CP-SAT model that finds a provably optimal (or best-within-time-limit)
production schedule in one shot.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from ortools.sat.python import cp_model

from .models import (
    ActorSchedule,
    LocationInfo,
    ProductionSchedule,
    ScheduleConfig,
    ShootingDay,
)

# Default scene shooting duration in hours (fallback when no estimate available)
_DEFAULT_SCENE_HOURS: float = 0.5

# Weekday name → weekday() mapping (0 = Monday … 6 = Sunday)
_WEEKDAY_MAP: dict[str, int] = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
    "星期五": 4, "星期六": 5, "星期日": 6,
}


# ---------------------------------------------------------------------------
# Date utilities
# ---------------------------------------------------------------------------

def _is_rest_day(d: date, rest_days: list[str]) -> bool:
    """Return True if *d* is a configured rest day (specific date or weekday name)."""
    date_str = d.strftime("%Y-%m-%d")
    if date_str in rest_days:
        return True
    wd = d.weekday()
    return any(_WEEKDAY_MAP.get(r) == wd for r in rest_days)


def _next_shooting_date(from_date: date, rest_days: list[str]) -> date:
    """Return the first non-rest day on or after *from_date*."""
    d = from_date
    while _is_rest_day(d, rest_days):
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# ScheduleOptimizer
# ---------------------------------------------------------------------------

class ScheduleOptimizer:
    """
    CP-SAT based production schedule optimizer.

    Decision variables
    ------------------
    x[i][t]        BoolVar — scene i assigned to shooting day t
    day_used[t]    BoolVar — day t has at least one scene
    loc_used[l][t] BoolVar — location l used on day t

    Objective (minimise)
    --------------------
    α·transition_cost + β·actor_cost + ε·total_days − continuity_bonus
    """

    def __init__(
        self,
        scenes: list[Any],            # list[Scene]
        entities: dict[int, dict],    # scene_number → {"characters": [...], ...}
        actors: list[ActorSchedule],
        locations: list[LocationInfo],
        config: ScheduleConfig,
    ) -> None:
        self.scenes = list(scenes)
        self.entities = entities
        self.actors = list(actors)
        self.locations = list(locations)
        self.config = config

        # ── Build auxiliary indices ──────────────────────────────────────────

        # scene_number → set[character_name]
        self._scene_chars: dict[int, set[str]] = {}
        # scene_number → location string
        self._scene_loc: dict[int, str] = {}
        # scene_number → duration (hours)
        self._scene_duration: dict[int, float] = {}
        # character_name → list[scene_number]
        self._char_scenes: dict[str, list[int]] = defaultdict(list)
        # location → list[scene_number]
        self._loc_scenes: dict[str, list[int]] = defaultdict(list)

        dur_map: dict[int, float] = getattr(self.config, 'scene_duration_map', None) or {}
        for scene in self.scenes:
            sn: int = scene.scene_number
            loc: str = scene.location or "未知场地"
            self._scene_loc[sn] = loc
            self._scene_duration[sn] = dur_map.get(sn, _DEFAULT_SCENE_HOURS)
            chars: set[str] = set(self.entities.get(sn, {}).get("characters", []))
            self._scene_chars[sn] = chars
            for c in chars:
                self._char_scenes[c].append(sn)
            self._loc_scenes[loc].append(sn)

        # character_name → set[date_str] of unavailable dates
        self._actor_unavailable: dict[str, set[str]] = {}
        for actor in self.actors:
            self._actor_unavailable[actor.character_name] = set(actor.unavailable_dates)

        # location → set[date_str] whitelist (empty set = no restriction)
        self._loc_available: dict[str, set[str]] = {}
        for loc_info in self.locations:
            if loc_info.available_dates:
                self._loc_available[loc_info.name] = set(loc_info.available_dates)

        # location → set[date_str] blacklist (accumulated by reschedule updates)
        self._loc_unavailable: dict[str, set[str]] = defaultdict(set)

        # Accumulated warnings from generate_safe data-cleaning and fallbacks
        self.warnings: list[str] = []

    # ── Public interface ─────────────────────────────────────────────────────

    def _estimate_max_days(self) -> int:
        """
        Upper bound on shooting days needed.

        每天有约3小时固定开销（妆发+餐休+缓冲），从可用时间中扣除，
        再给3倍余量确保CP-SAT有足够变量空间。
        下限取 len(scenes)//3（极端情况每3场一天）。
        """
        total_hours = sum(self._scene_duration.values()) if self._scene_duration else 0.0
        max_h = self.config.max_hours_per_day or 12
        # 每天扣除固定开销后的有效拍摄时间
        effective_h = max(max_h - 3, 4)
        raw = total_hours / effective_h
        return max(len(self.scenes) // 3, int(raw * 3) + 10)

    def solve(
        self,
        time_limit_seconds: float = 30,
        frozen_days: Optional[dict[str, list[int]]] = None,
        extra_constraints: Optional[list[dict]] = None,
        *,
        _relax_level: int = 0,
    ) -> ProductionSchedule:
        """
        Core CP-SAT solve.

        Parameters
        ----------
        time_limit_seconds:
            Wall-clock budget for the solver.
        frozen_days:
            {date_str: [scene_id, ...]} — pre-assigned days that are locked
            in place and not re-optimised.
        extra_constraints:
            Additional constraints injected by the LLM feedback loop.
            Each dict has keys:
              "type"   : "must_before" | "must_same_day" | "must_different_day"
                        | "must_not_date" | "prefer_consecutive"
              "scenes" : list[int]  (scene_number values)
              "params" : dict       (optional, type-specific)

            must_before       — scenes=[A, B]: A shot strictly before B
            must_same_day     — all listed scenes on the same day
            must_different_day— no two listed scenes on the same day
            must_not_date     — params={"date": "YYYY-MM-DD"}: scenes blocked
            prefer_consecutive— soft: adjacent scenes rewarded (bonus in obj)

        Returns
        -------
        ProductionSchedule with an optimal (or best feasible) assignment.

        Raises
        ------
        RuntimeError if the problem is proven infeasible.
        """
        frozen_days = frozen_days or {}

        # ── A. Prepare data ──────────────────────────────────────────────────

        frozen_scene_ids: set[int] = {
            sid for sids in frozen_days.values() for sid in sids
        }
        # Scenes to optimise (exclude already-frozen ones)
        all_scene_ids: list[int] = [
            s.scene_number for s in self.scenes
            if s.scene_number not in frozen_scene_ids
        ]

        if not all_scene_ids:
            return self._build_schedule_from_frozen(frozen_days)

        N = len(all_scene_ids)
        # scene list-index → scene_number
        sid_by_idx: list[int] = all_scene_ids
        # scene_number → list index (reverse map)
        sid_to_idx: dict[int, int] = {sid: i for i, sid in enumerate(sid_by_idx)}

        T = self._estimate_max_days()

        # Generate T consecutive non-rest shooting dates
        start_obj = datetime.strptime(self.config.start_date, "%Y-%m-%d").date()
        dates: list[date] = []
        d = _next_shooting_date(start_obj, self.config.rest_days)
        while len(dates) < T:
            dates.append(d)
            d = _next_shooting_date(d + timedelta(days=1), self.config.rest_days)
        date_strs: list[str] = [dt.strftime("%Y-%m-%d") for dt in dates]

        # Unique locations for the scenes being optimised
        all_locs: list[str] = sorted({
            self._scene_loc.get(sid, "未知场地") for sid in all_scene_ids
        })
        loc_to_lidx: dict[str, int] = {loc: i for i, loc in enumerate(all_locs)}
        L = len(all_locs)

        # Integer scene durations (scaled ×100 so CP-SAT can handle them)
        dur_int: list[int] = [
            int(self._scene_duration.get(sid, _DEFAULT_SCENE_HOURS) * 100)
            for sid in sid_by_idx
        ]
        max_hours_int: int = int(self.config.max_hours_per_day * 100)

        # Scene list-index → location list-index
        scene_lidx: list[int] = [
            loc_to_lidx[self._scene_loc.get(sid, "未知场地")]
            for sid in sid_by_idx
        ]

        # ── B. Create CP-SAT model ───────────────────────────────────────────

        model = cp_model.CpModel()

        # ── C. Decision variables ────────────────────────────────────────────

        # x[i][t] = 1  ↔  scene i is shot on day t
        x: list[list[cp_model.IntVar]] = [
            [model.NewBoolVar(f"x_{i}_{t}") for t in range(T)]
            for i in range(N)
        ]

        # day_used[t] = 1  ↔  at least one scene is shot on day t
        day_used: list[cp_model.IntVar] = [
            model.NewBoolVar(f"day_{t}") for t in range(T)
        ]

        # loc_used[l][t] = 1  ↔  location l is used on day t
        loc_used: list[list[cp_model.IntVar]] = [
            [model.NewBoolVar(f"lu_{l}_{t}") for t in range(T)]
            for l in range(L)
        ]

        # ── D. Hard constraints ──────────────────────────────────────────────

        level: str = getattr(self.config, 'constraint_level', 'relaxed')
        penalty_vars: list[cp_model.IntVar] = []
        PENALTY = 10000

        # ① Each scene assigned to exactly one day
        for i in range(N):
            model.AddExactlyOne([x[i][t] for t in range(T)])

        # ② Daily hours ≤ max_hours_per_day  (all values scaled ×100)
        for t in range(T):
            model.Add(
                sum(dur_int[i] * x[i][t] for i in range(N)) <= max_hours_int
            )

        # ③ Actor conflict: same actor cannot work at two different locations
        #    on the same day.
        #    Hard in strict/standard mode; soft penalty in relaxed mode.
        for char_name in self._char_scenes:
            # Group actor's scenes by location (only the ones being optimised)
            loc_groups: dict[str, list[int]] = defaultdict(list)
            for sn in self._char_scenes[char_name]:
                if sn in sid_to_idx:
                    loc = self._scene_loc.get(sn, "未知场地")
                    loc_groups[loc].append(sid_to_idx[sn])
            if len(loc_groups) < 2:
                continue  # actor only at one location — no conflict possible
            locs_list = list(loc_groups.keys())
            for li in range(len(locs_list)):
                for lj in range(li + 1, len(locs_list)):
                    for i1 in loc_groups[locs_list[li]]:
                        for i2 in loc_groups[locs_list[lj]]:
                            for t in range(T):
                                if level in ("strict", "standard"):
                                    model.Add(x[i1][t] + x[i2][t] <= 1)
                                else:  # relaxed: soft penalty
                                    v = model.NewBoolVar(
                                        f"v3_{i1}_{i2}_{t}"
                                    )
                                    model.Add(
                                        x[i1][t] + x[i2][t] <= 1
                                    ).OnlyEnforceIf(v.Not())
                                    penalty_vars.append(v)

        # ④ Actor unavailability: scene involving an unavailable actor
        #    cannot be scheduled on that date.
        #    Hard in strict mode; soft penalty in standard/relaxed mode.
        #    Skipped entirely at _relax_level ≥ 2.
        if _relax_level < 2:
            for char_name, unavail in self._actor_unavailable.items():
                if not unavail:
                    continue
                for sn in self._char_scenes.get(char_name, []):
                    if sn not in sid_to_idx:
                        continue
                    i = sid_to_idx[sn]
                    for t, ds in enumerate(date_strs):
                        if ds in unavail:
                            if level == "strict":
                                model.Add(x[i][t] == 0)
                            else:  # standard or relaxed: soft penalty
                                v = model.NewBoolVar(f"v4_{i}_{t}")
                                model.Add(x[i][t] == 0).OnlyEnforceIf(v.Not())
                                penalty_vars.append(v)

        # ⑤ Location availability
        #    Two mechanisms can restrict a location:
        #    (a) whitelist  (_loc_available[loc] ≠ ∅): only those dates are OK
        #    (b) blacklist  (_loc_unavailable[loc]):    those dates are blocked
        #    At _relax_level ≥ 3 the whitelist is ignored (only blacklist kept).
        #    Hard in strict mode; soft penalty in standard/relaxed mode.
        for loc in all_locs:
            avail = self._loc_available.get(loc, set()) if _relax_level < 3 else set()
            unavail = self._loc_unavailable.get(loc, set())
            if not avail and not unavail:
                continue  # no restriction for this location
            scene_idxs_at_loc = [
                sid_to_idx[sn]
                for sn in self._loc_scenes.get(loc, [])
                if sn in sid_to_idx
            ]
            for t, ds in enumerate(date_strs):
                blocked = (avail and ds not in avail) or (ds in unavail)
                if blocked:
                    for i in scene_idxs_at_loc:
                        if level == "strict":
                            model.Add(x[i][t] == 0)
                        else:  # standard or relaxed: soft penalty
                            v = model.NewBoolVar(f"v5_{i}_{t}")
                            model.Add(x[i][t] == 0).OnlyEnforceIf(v.Not())
                            penalty_vars.append(v)

        # ⑥ day_used linkage: day_used[t] = max(x[i][t] for all i)
        #    i.e. day_used[t] = 1 iff any scene is assigned to day t
        for t in range(T):
            model.AddMaxEquality(day_used[t], [x[i][t] for i in range(N)])

        # ⑦ loc_used linkage: loc_used[l][t] = max(x[i][t] for i at location l)
        for l in range(L):
            scenes_at_l = [i for i in range(N) if scene_lidx[i] == l]
            # scenes_at_l is always non-empty: all_locs derived from all_scene_ids
            for t in range(T):
                model.AddMaxEquality(loc_used[l][t], [x[i][t] for i in scenes_at_l])

        # ── E. Objective function (minimise) ─────────────────────────────────
        #
        # All float weights are scaled to integers by SCALE = 1000.
        # daily_rate values are already in CNY (integers after truncation).
        #
        # Total cost = α·transition + β·actor_wages + ε·days − continuity_bonus

        SCALE = 1000
        w_trans = int(self.config.weight_transition * SCALE)
        w_actor = int(self.config.weight_actor * SCALE)
        w_days  = int(self.config.weight_days  * SCALE)

        obj_vars:   list[cp_model.IntVar] = []
        obj_coeffs: list[int]             = []

        # 1. Transition cost: penalise total (location, day) pairs used
        for l in range(L):
            for t in range(T):
                obj_vars.append(loc_used[l][t])
                obj_coeffs.append(w_trans)

        # 2. Actor cost: each actor's working days × daily rate
        for actor in self.actors:
            rate = min(int(actor.daily_rate), 10_000_000)  # cap to avoid overflow
            if rate <= 0:
                continue
            char_name = actor.character_name
            actor_scene_idxs = [
                sid_to_idx[sn]
                for sn in self._char_scenes.get(char_name, [])
                if sn in sid_to_idx
            ]
            if not actor_scene_idxs:
                continue
            coeff = w_actor * rate
            for t in range(T):
                awd = model.NewBoolVar(f"awd_{char_name}_{t}")
                model.AddMaxEquality(awd, [x[i][t] for i in actor_scene_idxs])
                obj_vars.append(awd)
                obj_coeffs.append(coeff)

        # 3. Total shooting days
        for t in range(T):
            obj_vars.append(day_used[t])
            obj_coeffs.append(w_days)

        # 4. Location continuity bonus (negative cost):
        #    if the same location is used on two consecutive days, reduce cost.
        continuity_bonus = max(w_trans // 2, 1)
        for l in range(L):
            for t in range(T - 1):
                cont = model.NewBoolVar(f"cont_{l}_{t}")
                # cont = 1 iff loc_used[l][t] AND loc_used[l][t+1]
                model.AddMinEquality(cont, [loc_used[l][t], loc_used[l][t + 1]])
                obj_vars.append(cont)
                obj_coeffs.append(-continuity_bonus)

        # ── E'. Extra constraints from LLM feedback ──────────────────────────
        #
        # Hard types (must_before / must_same_day / must_different_day /
        #             must_not_date) are added directly to the model.
        # Soft type (prefer_consecutive) adds negative-bonus terms to the
        # objective via obj_vars / obj_coeffs — they must be appended
        # BEFORE model.Minimize is called below.

        for c in (extra_constraints if _relax_level < 1 else []) or []:
            ctype   = c.get("type", "")
            scenes  = c.get("scenes", [])
            params  = c.get("params") or {}

            # Resolve scene numbers → variable indices (skip unknown IDs)
            idxs = [sid_to_idx[s] for s in scenes if s in sid_to_idx]

            if ctype == "must_before":
                # scenes=[A, B]: day_of(A) < day_of(B)
                # Encoded as: Σ_t t·x[A][t] + 1 ≤ Σ_t t·x[B][t]
                if len(idxs) >= 2:
                    a_idx, b_idx = idxs[0], idxs[1]
                    sum_a = cp_model.LinearExpr.WeightedSum(
                        [x[a_idx][t] for t in range(T)], list(range(T))
                    )
                    sum_b = cp_model.LinearExpr.WeightedSum(
                        [x[b_idx][t] for t in range(T)], list(range(T))
                    )
                    model.Add(sum_b >= sum_a + 1)

            elif ctype == "must_same_day":
                # All scenes in the list must be on the same day.
                # For each pair (ia, ib) and each day t: x[ia][t] == x[ib][t]
                for ki in range(len(idxs)):
                    for kj in range(ki + 1, len(idxs)):
                        ia, ib = idxs[ki], idxs[kj]
                        for t in range(T):
                            model.Add(x[ia][t] == x[ib][t])

            elif ctype == "must_different_day":
                # No two listed scenes may share a day.
                for ki in range(len(idxs)):
                    for kj in range(ki + 1, len(idxs)):
                        ia, ib = idxs[ki], idxs[kj]
                        for t in range(T):
                            model.Add(x[ia][t] + x[ib][t] <= 1)

            elif ctype == "must_not_date":
                # Block listed scenes from a specific calendar date.
                date_str = str(params.get("date", ""))
                if date_str in date_strs:
                    t_blocked = date_strs.index(date_str)
                    for i in idxs:
                        model.Add(x[i][t_blocked] == 0)

            elif ctype == "prefer_consecutive":
                # Soft: reward placing scene pairs on adjacent days.
                # For each ordered pair (i, j) and each day t:
                #   consec_var = x[i][t] AND x[j][t+1]  (or reversed)
                # → subtract bonus from objective for each such var = 1
                bonus = int(params.get("bonus", w_trans // 2 + 1))
                for ki in range(len(idxs)):
                    for kj in range(ki + 1, min(ki + 6, len(idxs))):
                        ia, ib = idxs[ki], idxs[kj]
                        for t in range(T - 1):
                            # ia on day t, ib on day t+1
                            v1 = model.NewBoolVar(f"ec_c_{ia}_{ib}_{t}a")
                            model.AddMinEquality(v1, [x[ia][t], x[ib][t + 1]])
                            obj_vars.append(v1)
                            obj_coeffs.append(-bonus)
                            # ib on day t, ia on day t+1
                            v2 = model.NewBoolVar(f"ec_c_{ia}_{ib}_{t}b")
                            model.AddMinEquality(v2, [x[ib][t], x[ia][t + 1]])
                            obj_vars.append(v2)
                            obj_coeffs.append(-bonus)

        # Soft-constraint penalties (relaxed / standard modes)
        for v in penalty_vars:
            obj_vars.append(v)
            obj_coeffs.append(PENALTY)

        model.Minimize(cp_model.LinearExpr.WeightedSum(obj_vars, obj_coeffs))

        # ── F. Solve ─────────────────────────────────────────────────────────

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = getattr(
            self.config, 'solver_time_limit', 30
        )
        solver.parameters.num_workers = 8
        status = solver.Solve(model)

        # ── G. Extract results ───────────────────────────────────────────────

        # UNKNOWN = timeout without any feasible solution found
        if status == cp_model.UNKNOWN:
            try:
                # Check if solver has a partial solution we can extract
                _ = solver.Value(x[0][0])
                status = cp_model.FEASIBLE  # treat as feasible, fall through
            except Exception:
                tl = getattr(self.config, 'solver_time_limit', 30)
                raise RuntimeError(f"求解超时({tl}秒)，未找到可行解")

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # ── Cascade relaxation: progressively drop constraints and retry ──
            # Level 1: Drop extra_constraints (LLM suggestions may conflict)
            if _relax_level == 0 and extra_constraints:
                logger.warning(
                    "CP-SAT infeasible with extra constraints; retrying without them…"
                )
                sched = self.solve(
                    time_limit_seconds, frozen_days, extra_constraints,
                    _relax_level=1,
                )
                sched._relaxation_note = (
                    "排期提示：LLM 建议约束与其他约束冲突，已自动忽略（结果仍为最优解）。"
                )
                return sched

            # Level 2: Drop actor unavailability constraints
            if _relax_level <= 1 and any(self._actor_unavailable.values()):
                logger.warning(
                    "CP-SAT still infeasible; retrying without actor unavailability…"
                )
                sched = self.solve(
                    time_limit_seconds, frozen_days, None,
                    _relax_level=2,
                )
                sched._relaxation_note = (
                    "排期提示：演员档期约束已放宽（档期窗口不足），请手动确认演员可用性。"
                )
                return sched

            # Level 3: Drop location whitelist (keep blacklist)
            if _relax_level <= 2 and any(self._loc_available.values()):
                logger.warning(
                    "CP-SAT still infeasible; retrying without location whitelist…"
                )
                sched = self.solve(
                    time_limit_seconds, frozen_days, None,
                    _relax_level=3,
                )
                sched._relaxation_note = (
                    "排期提示：场地可用日期约束已放宽（窗口过窄），请手动确认场地档期。"
                )
                return sched

            raise RuntimeError(
                f"无法满足所有约束，请放宽条件 "
                f"(solver status: {solver.StatusName(status)})"
            )

        # Map day index → list of assigned scene_numbers
        day_to_scenes: dict[int, list[int]] = defaultdict(list)
        for i in range(N):
            for t in range(T):
                if solver.Value(x[i][t]):
                    day_to_scenes[t].append(sid_by_idx[i])
                    break  # AddExactlyOne guarantees exactly one t per scene

        # Build ShootingDay objects for optimised days
        shooting_days: list[ShootingDay] = []
        for t in sorted(day_to_scenes.keys()):
            scene_ids_today = day_to_scenes[t]
            loc_counts: dict[str, int] = defaultdict(int)
            for sid in scene_ids_today:
                loc_counts[self._scene_loc.get(sid, "未知场地")] += 1
            main_loc = max(loc_counts, key=loc_counts.__getitem__)
            shooting_days.append(ShootingDay(
                date=date_strs[t],
                day_number=0,        # renumbered after merge
                scene_ids=scene_ids_today,
                location=main_loc,
            ))

        # Append frozen (completed) days
        for date_str, scene_ids in sorted(frozen_days.items()):
            if not scene_ids:
                continue
            loc_counts = defaultdict(int)
            for sid in scene_ids:
                loc_counts[self._scene_loc.get(sid, "未知场地")] += 1
            main_loc = max(loc_counts, key=loc_counts.__getitem__) if loc_counts else ""
            shooting_days.append(ShootingDay(
                date=date_str,
                day_number=0,
                scene_ids=list(scene_ids),
                location=main_loc,
                status="completed",
            ))

        # Sort by date and assign sequential day numbers
        shooting_days.sort(key=lambda day: day.date)
        for i, day in enumerate(shooting_days):
            day.day_number = i + 1

        end_date = shooting_days[-1].date if shooting_days else self.config.start_date
        return ProductionSchedule(
            shooting_days=shooting_days,
            actors=list(self.actors),
            locations=list(self.locations),
            config=self.config,
            start_date=self.config.start_date,
            end_date=end_date,
        )

    # ── Incremental reschedule ────────────────────────────────────────────────

    def reschedule(
        self,
        current: ProductionSchedule,
        change_type: str,
        change_data: dict,
    ) -> dict:
        """
        Incremental reschedule after a production change.

        Steps
        -----
        1. Lock completed days as frozen_days.
        2. Apply constraint changes to internal state (actor/location/scenes).
        3. Call self.solve(frozen_days=frozen) to re-optimise everything else.
        4. Restore original ShootingDay metadata for frozen days.
        5. Return {"schedule": …, "diff": …, "impact": …}.

        change_type / change_data formats
        ----------------------------------
        "weather"       {"date": "YYYY-MM-DD"}
        "actor"         {"character_name": str,
                         "unavailable_dates": [str, ...]}
        "script_add"    {"scene_ids": [int, ...]}   (scenes already in self.scenes)
        "script_remove" {"scene_ids": [int, ...]}
        "location"      {"location_name": str,
                         "unavailable_dates": [str, ...]}
        """
        # ① Lock completed days
        frozen: dict[str, list[int]] = {}
        frozen_day_objects: dict[str, ShootingDay] = {}
        for day in current.shooting_days:
            if day.status == "completed":
                frozen[day.date] = list(day.scene_ids)
                frozen_day_objects[day.date] = day

        # ② Apply constraint changes
        if change_type == "actor":
            char_name = change_data.get("character_name", "")
            new_unavail = set(change_data.get("unavailable_dates", []))
            self._actor_unavailable.setdefault(char_name, set()).update(new_unavail)
            for actor in self.actors:
                if actor.character_name == char_name:
                    actor.unavailable_dates = sorted(
                        set(actor.unavailable_dates) | new_unavail
                    )

        elif change_type == "location":
            loc_name = change_data.get("location_name", "")
            new_unavail = set(change_data.get("unavailable_dates", []))
            # Add to blacklist
            self._loc_unavailable[loc_name].update(new_unavail)
            # Also shrink whitelist if it exists
            if loc_name in self._loc_available:
                self._loc_available[loc_name] -= new_unavail
            for loc_info in self.locations:
                if loc_info.name == loc_name and loc_info.available_dates:
                    loc_info.available_dates = sorted(
                        set(loc_info.available_dates) - new_unavail
                    )

        elif change_type == "script_remove":
            remove_ids = set(change_data.get("scene_ids", []))
            self.scenes = [s for s in self.scenes if s.scene_number not in remove_ids]
            # Update per-scene indices
            for sid in remove_ids:
                old_loc = self._scene_loc.pop(sid, None)
                self._scene_chars.pop(sid, None)
                self._scene_duration.pop(sid, None)
                if old_loc is not None:
                    try:
                        self._loc_scenes[old_loc].remove(sid)
                    except ValueError:
                        pass
            # Rebuild _char_scenes from remaining scenes
            self._char_scenes = defaultdict(list)
            for scene in self.scenes:
                sn = scene.scene_number
                for c in self._scene_chars.get(sn, set()):
                    self._char_scenes[c].append(sn)

        # change_type "weather" and "script_add" need no internal-state update:
        # affected scenes are simply not frozen, so they will be re-optimised.

        # ③ Re-solve
        new_schedule = self.solve(time_limit_seconds=30, frozen_days=frozen)

        # ④ Restore original ShootingDay metadata for frozen days
        for day in new_schedule.shooting_days:
            if day.date in frozen_day_objects:
                orig = frozen_day_objects[day.date]
                day.call_time       = orig.call_time
                day.estimated_end   = orig.estimated_end
                day.notes           = orig.notes
                day.weather_backup  = orig.weather_backup
                day.status          = orig.status

        # ⑤ Compute diff
        old_day_map = {d.date: set(d.scene_ids) for d in current.shooting_days}
        new_day_map = {d.date: set(d.scene_ids) for d in new_schedule.shooting_days}
        old_dates = set(old_day_map)
        new_dates = set(new_day_map)

        added_days   = sorted(new_dates - old_dates)
        removed_days = sorted(old_dates - new_dates)
        changed_days = sorted(
            dt for dt in old_dates & new_dates
            if old_day_map[dt] != new_day_map[dt]
        )

        affected: set[int] = set()
        for dt in added_days + changed_days:
            affected.update(new_day_map.get(dt, set()))
        for dt in removed_days:
            affected.update(old_day_map.get(dt, set()))

        return {
            "schedule": new_schedule,
            "diff": {
                "added_days":   added_days,
                "removed_days": removed_days,
                "changed_days": changed_days,
            },
            "impact": {
                "affected_scenes": len(affected),
                "affected_days":   len(added_days) + len(removed_days) + len(changed_days),
            },
        }

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _build_schedule_from_frozen(
        self, frozen_days: dict[str, list[int]]
    ) -> ProductionSchedule:
        """Build a ProductionSchedule entirely from pre-frozen days (no optimisation)."""
        days: list[ShootingDay] = []
        for date_str, scene_ids in sorted(frozen_days.items()):
            if not scene_ids:
                continue
            loc_counts: dict[str, int] = defaultdict(int)
            for sid in scene_ids:
                loc_counts[self._scene_loc.get(sid, "未知场地")] += 1
            main_loc = max(loc_counts, key=loc_counts.__getitem__) if loc_counts else ""
            days.append(ShootingDay(
                date=date_str,
                day_number=0,
                scene_ids=list(scene_ids),
                location=main_loc,
                status="completed",
            ))
        for i, day in enumerate(days):
            day.day_number = i + 1
        end_date = days[-1].date if days else self.config.start_date
        return ProductionSchedule(
            shooting_days=days,
            actors=list(self.actors),
            locations=list(self.locations),
            config=self.config,
            start_date=self.config.start_date,
            end_date=end_date,
        )

    # ── Safe generation (never raises) ───────────────────────────────────────

    def generate_safe(
        self,
        time_limit_seconds: float = 10,
        extra_constraints: Optional[list[dict]] = None,
    ) -> ProductionSchedule:
        """Generate a schedule that never raises.

        Tries four strategies in order:
        1. Normal CP-SAT solve
        2. Relaxed CP-SAT (wider max_hours_per_day)
        3. Greedy grouping by location (_fallback_group_by_location)
        4. Brute-force sequential packing (_ultimate_fallback)

        The returned ProductionSchedule always has .warnings and .solver_status set.
        """
        self.warnings = []

        # ── 时长摘要（最先插入，方便前端展示）──────────────────────────────
        total_h = sum(self._scene_duration.values()) if self._scene_duration else 0.0
        max_h = self.config.max_hours_per_day or 12
        est_days = max(1, math.ceil(total_h / max(max_h - 3, 4)))
        self.warnings.insert(0,
            f"总预估拍摄时长: {total_h:.1f}小时, 约{est_days}天(按{max_h}h/天扣除固定开销)")

        # ── Data cleaning ────────────────────────────────────────────────────
        for s in self.scenes:
            loc = getattr(s, "location", None)
            if not loc or not str(loc).strip():
                s.location = "未指定场地"
                self.warnings.append(
                    f"场次{s.scene_number}缺少地点，归入「未指定场地」"
                )
            if not getattr(s, "int_ext", None):
                s.int_ext = "内"
            if not getattr(s, "time_of_day", None):
                s.time_of_day = "日"

        # Rebuild indexes to reflect cleaned data
        self._safe_rebuild_indexes()

        # ── Attempt 1: normal solve ──────────────────────────────────────────
        try:
            result = self.solve(
                time_limit_seconds=time_limit_seconds,
                extra_constraints=extra_constraints,
            )
            if result and getattr(result, "shooting_days", None):
                result.warnings = list(self.warnings)
                result.solver_status = "optimal"
                return result
            self.warnings.append("求解器返回空结果")
        except Exception as e:
            self.warnings.append(f"求解器失败({type(e).__name__}: {e})")

        # ── Attempt 2: relaxed max_hours ─────────────────────────────────────
        saved_hours = self.config.max_hours_per_day
        try:
            self.config.max_hours_per_day = max(saved_hours * 1.5, 16)
            self.warnings.append(f"放宽工时至{self.config.max_hours_per_day}h重试")
            result = self.solve(
                time_limit_seconds=time_limit_seconds,
                extra_constraints=None,
            )
            self.config.max_hours_per_day = saved_hours
            if result and getattr(result, "shooting_days", None):
                result.warnings = list(self.warnings)
                result.solver_status = "relaxed"
                return result
        except Exception as e:
            self.config.max_hours_per_day = saved_hours
            self.warnings.append(f"放宽后仍失败: {e}")

        # ── Attempt 3: greedy grouping by location ───────────────────────────
        try:
            result = self._fallback_group_by_location()
            if result and result.shooting_days:
                self.warnings.append("使用简单分组（未优化），建议手动调整")
                result.warnings = list(self.warnings)
                result.solver_status = "fallback"
                return result
        except Exception as e:
            self.warnings.append(f"分组失败: {e}")

        # ── Attempt 4: ultimate sequential fallback ──────────────────────────
        result = self._ultimate_fallback()
        result.warnings = list(self.warnings)
        result.solver_status = "emergency"
        return result

    def _safe_rebuild_indexes(self) -> None:
        """Rebuild all auxiliary index dicts from self.scenes / self.entities / self.actors / self.locations."""
        self._scene_chars = {}
        self._scene_loc = {}
        self._scene_duration = {}
        self._char_scenes: dict[str, list[int]] = defaultdict(list)
        self._loc_scenes: dict[str, list[int]] = defaultdict(list)

        dur_map: dict[int, float] = getattr(self.config, 'scene_duration_map', None) or {}
        for scene in self.scenes:
            sn: int = scene.scene_number
            loc: str = scene.location or "未知场地"
            self._scene_loc[sn] = loc
            self._scene_duration[sn] = dur_map.get(sn, _DEFAULT_SCENE_HOURS)
            chars: set[str] = set(self.entities.get(sn, {}).get("characters", []))
            self._scene_chars[sn] = chars
            for c in chars:
                self._char_scenes[c].append(sn)
            self._loc_scenes[loc].append(sn)

        # Rebuild actor unavailability index
        self._actor_unavailable = {}
        for actor in self.actors:
            self._actor_unavailable[actor.character_name] = set(actor.unavailable_dates)

        # Rebuild location availability index (preserve existing blacklist)
        self._loc_available = {}
        for loc_info in self.locations:
            if loc_info.available_dates:
                self._loc_available[loc_info.name] = set(loc_info.available_dates)
        # _loc_unavailable blacklist is intentionally preserved (set in reschedule)

    def _fallback_group_by_location(self) -> ProductionSchedule:
        """Greedy schedule: group scenes by location, pack into days by hours budget."""
        max_hours = max(self.config.max_hours_per_day, 0.5)
        start_obj = datetime.strptime(self.config.start_date, "%Y-%m-%d").date()
        current_date = _next_shooting_date(start_obj, self.config.rest_days)

        # Group scenes by location, preserving insertion order within each group
        loc_groups: dict[str, list] = {}
        for scene in self.scenes:
            loc = self._scene_loc.get(scene.scene_number, "未指定场地")
            loc_groups.setdefault(loc, []).append(scene)

        shooting_days: list[ShootingDay] = []

        for loc, scenes_in_loc in loc_groups.items():
            current_hours: float = 0.0
            current_scene_ids: list[int] = []

            for scene in scenes_in_loc:
                dur = self._scene_duration.get(scene.scene_number, _DEFAULT_SCENE_HOURS)
                if current_scene_ids and current_hours + dur > max_hours:
                    # Flush current day
                    shooting_days.append(ShootingDay(
                        date=current_date.strftime("%Y-%m-%d"),
                        day_number=0,
                        scene_ids=list(current_scene_ids),
                        location=loc,
                    ))
                    current_date = _next_shooting_date(
                        current_date + timedelta(days=1), self.config.rest_days
                    )
                    current_scene_ids = []
                    current_hours = 0.0
                current_scene_ids.append(scene.scene_number)
                current_hours += dur

            # Flush remaining scenes in this location group
            if current_scene_ids:
                shooting_days.append(ShootingDay(
                    date=current_date.strftime("%Y-%m-%d"),
                    day_number=0,
                    scene_ids=list(current_scene_ids),
                    location=loc,
                ))
                current_date = _next_shooting_date(
                    current_date + timedelta(days=1), self.config.rest_days
                )

        shooting_days.sort(key=lambda d: d.date)
        for i, day in enumerate(shooting_days):
            day.day_number = i + 1

        end_date = shooting_days[-1].date if shooting_days else self.config.start_date
        return ProductionSchedule(
            shooting_days=shooting_days,
            actors=list(self.actors),
            locations=list(self.locations),
            config=self.config,
            start_date=self.config.start_date,
            end_date=end_date,
        )

    def _ultimate_fallback(self) -> ProductionSchedule:
        """Sequential packing: scenes in scene_number order, packed by real duration.

        This cannot fail as long as self.scenes is iterable.
        """
        max_hours = max(self.config.max_hours_per_day, 0.5)
        sorted_scenes = sorted(self.scenes, key=lambda s: s.scene_number)

        start_obj = datetime.strptime(self.config.start_date, "%Y-%m-%d").date()
        current_date = _next_shooting_date(start_obj, self.config.rest_days)

        shooting_days: list[ShootingDay] = []
        current_scene_ids: list[int] = []
        current_hours: float = 0.0

        for scene in sorted_scenes:
            dur = self._scene_duration.get(scene.scene_number, _DEFAULT_SCENE_HOURS)
            if current_scene_ids and current_hours + dur > max_hours:
                # Flush current day
                loc_counts: dict[str, int] = defaultdict(int)
                for sid in current_scene_ids:
                    loc_counts[self._scene_loc.get(sid, "未指定场地")] += 1
                main_loc = max(loc_counts, key=loc_counts.__getitem__)
                shooting_days.append(ShootingDay(
                    date=current_date.strftime("%Y-%m-%d"),
                    day_number=0,
                    scene_ids=list(current_scene_ids),
                    location=main_loc,
                ))
                current_date = _next_shooting_date(
                    current_date + timedelta(days=1), self.config.rest_days
                )
                current_scene_ids = []
                current_hours = 0.0
            current_scene_ids.append(scene.scene_number)
            current_hours += dur

        # Flush remaining scenes
        if current_scene_ids:
            loc_counts = defaultdict(int)
            for sid in current_scene_ids:
                loc_counts[self._scene_loc.get(sid, "未指定场地")] += 1
            main_loc = max(loc_counts, key=loc_counts.__getitem__) if loc_counts else "未指定场地"
            shooting_days.append(ShootingDay(
                date=current_date.strftime("%Y-%m-%d"),
                day_number=0,
                scene_ids=list(current_scene_ids),
                location=main_loc,
            ))
            current_date = _next_shooting_date(
                current_date + timedelta(days=1), self.config.rest_days
            )

        # Edge case: no scenes at all — return one empty day so the caller always
        # gets a valid ProductionSchedule with at least one entry.
        if not shooting_days:
            shooting_days.append(ShootingDay(
                date=current_date.strftime("%Y-%m-%d"),
                day_number=1,
                scene_ids=[],
                location="",
            ))

        for i, day in enumerate(shooting_days):
            day.day_number = i + 1

        end_date = shooting_days[-1].date if shooting_days else self.config.start_date
        return ProductionSchedule(
            shooting_days=shooting_days,
            actors=list(self.actors),
            locations=list(self.locations),
            config=self.config,
            start_date=self.config.start_date,
            end_date=end_date,
        )
