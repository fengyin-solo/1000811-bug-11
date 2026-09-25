"""泊位计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "berth"
REQUIRED_FIELDS = ["计划编号", "泊位编号", "靠泊船舶"]
# 登记/编排时允许写入的字段；之前只落了必填三项，计划靠离泊时间被丢弃，
# 看板与列表读不到同一份编排数据。这里把编排字段一并纳入落库。
EDITABLE_FIELDS = [
    "计划编号",
    "泊位编号",
    "靠泊船舶",
    "计划靠泊时间",
    "计划离泊时间",
    "船长",
    "吃水深度",
]
START_FIELD = "计划靠泊时间"
END_FIELD = "计划离泊时间"
STATUS_ORDER = ["待编排", "已编排", "已靠泊", "已离泊"]
ACTION_RULES = {"确认编排": "已编排", "确认靠泊": "已靠泊", "确认离泊": "已离泊"}
NEGATIVE_ACTIONS = []
# 已离泊的计划已释放泊位，不再参与占用冲突校验。
OCCUPYING_STATUSES = {"待编排", "已编排", "已靠泊"}


class BerthService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        berth: str | None = None,
        date: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if berth:
            rows = [row for row in rows if berth in str(row.get("泊位编号", ""))]
        if date:
            rows = [row for row in rows if self._occupies_date(row, date)]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        message = self._validate_schedule(values)
        if message:
            return None, message
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in EDITABLE_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        conflict = self._find_overlap(entry)
        if conflict is not None:
            return None, self._conflict_message(conflict)
        rows.append(entry)
        return entry, ""

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        merged = {field: entry.get(field) for field in EDITABLE_FIELDS}
        merged.update(
            {field: values[field] for field in EDITABLE_FIELDS if field in values}
        )
        message = self._validate_schedule(merged)
        if message:
            return None, message
        conflict = self._find_overlap(merged, exclude_id=entry_id)
        if conflict is not None:
            return None, self._conflict_message(conflict)
        # 校验全部通过后再把编排字段落库，保证看板与列表读到的是同一份数据。
        entry.update(merged)
        return entry, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于泊位计划可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if action == "确认编排":
            conflict = self._find_overlap(entry, exclude_id=entry_id)
            if conflict is not None:
                return None, self._conflict_message(conflict)
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"泊位计划已{action}"

    @staticmethod
    def _validate_schedule(values: dict[str, Any]) -> str:
        raw_start = str(values.get(START_FIELD) or "").strip()
        raw_end = str(values.get(END_FIELD) or "").strip()
        if bool(raw_start) != bool(raw_end):
            return "计划靠泊时间与计划离泊时间必须同时填写"
        interval = BerthService._interval(raw_start, raw_end)
        if interval and interval[1] < interval[0]:
            return "计划离泊时间不能早于计划靠泊时间"
        return ""

    @staticmethod
    def _interval(start: str, end: str) -> tuple[str, str] | None:
        """把日期/时间统一成「YYYY-MM-DD HH:MM」区间。

        只有日期的计划视为占用当天 00:00~23:59，避免日期粒度与分钟粒度
        的值直接按字符串比较导致漏判。
        """
        start = start.strip().replace("T", " ")
        end = end.strip().replace("T", " ")
        if not start or not end or len(start) < 10 or len(end) < 10:
            return None

        def bound(value: str, is_end: bool) -> str:
            day = value[:10]
            clock = value[11:16] if len(value) > 10 else ("23:59" if is_end else "00:00")
            return f"{day} {clock}"

        return bound(start, False), bound(end, True)

    @staticmethod
    def _occupies_date(row: dict[str, Any], date: str) -> bool:
        """日期与「靠泊—离泊」占用窗口有交集即命中。"""
        interval = BerthService._interval(
            str(row.get(START_FIELD) or ""), str(row.get(END_FIELD) or "")
        )
        day = date.strip().replace("T", " ")[:10]
        if interval is None or len(day) != 10:
            return False
        start, end = interval
        return start <= f"{day} 23:59" and end >= f"{day} 00:00"

    def _find_overlap(
        self, candidate: dict[str, Any], *, exclude_id: int | None = None
    ) -> dict[str, Any] | None:
        berth = str(candidate.get("泊位编号") or "").strip()
        interval = self._interval(
            str(candidate.get(START_FIELD) or ""), str(candidate.get(END_FIELD) or "")
        )
        if not berth or interval is None:
            return None
        start, end = interval
        for row in store.rows(MODULE):
            if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
                continue
            if str(row.get("泊位编号") or "").strip() != berth:
                continue
            if row.get("status") not in OCCUPYING_STATUSES:
                continue
            other = self._interval(
                str(row.get(START_FIELD) or ""), str(row.get(END_FIELD) or "")
            )
            if other is None:
                continue
            other_start, other_end = other
            # 端点相接视为同一泊位仍被占用。
            if start <= other_end and other_start <= end:
                return row
        return None

    @staticmethod
    def _conflict_message(conflict: dict[str, Any]) -> str:
        return (
            f"泊位「{conflict.get('泊位编号')}」在该时段已被计划 "
            f"{conflict.get('计划编号')}（{conflict.get(START_FIELD)} ~ "
            f"{conflict.get(END_FIELD)}，{conflict.get('靠泊船舶')}）占用，请调整时间或泊位"
        )
