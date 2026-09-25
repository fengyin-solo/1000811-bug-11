"""泊位计划业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "berth"
REQUIRED_FIELDS = ["计划编号", "泊位编号", "靠泊船舶"]
EDITABLE_FIELDS = ["泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度"]
STATUS_ORDER = ["待编排", "已编排", "已靠泊", "已离泊"]
ACTION_RULES = {"确认编排": "已编排", "确认靠泊": "已靠泊", "确认离泊": "已离泊"}
NEGATIVE_ACTIONS = []
TIME_FORMAT = "%Y-%m-%d %H:%M"


def _parse_time(value: Any) -> datetime | None:
    """把 '2026-09-25' 或 '2026-09-25 08:00'（也接受 T 分隔）解析成时间；无法识别时返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _format_time(value: datetime) -> str:
    return value.strftime(TIME_FORMAT)


def _window_of(row: dict[str, Any]) -> tuple[datetime, datetime] | None:
    start = _parse_time(row.get("计划靠泊时间"))
    end = _parse_time(row.get("计划离泊时间"))
    if start is None or end is None:
        return None
    return start, end


def _covers_date(row: dict[str, Any], day_text: str) -> bool:
    """按日期筛选：计划占用窗口覆盖该日即命中；时间缺失时退化为靠泊时间的日期前缀匹配。"""
    day = _parse_time(day_text)
    if day is None:
        return False
    window = _window_of(row)
    if window is None:
        return str(row.get("计划靠泊时间") or "").startswith(day_text)
    start, end = window
    return start.date() <= day.date() <= end.date()


class BerthService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        berth: str | None = None,
        vessel: str | None = None,
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
        if vessel:
            rows = [row for row in rows if vessel in str(row.get("靠泊船舶", ""))]
        if date:
            rows = [row for row in rows if _covers_date(row, date)]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        problems = self._validate_schedule(values)
        if problems:
            return None, problems
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["计划编号", *EDITABLE_FIELDS]:
            entry[field] = self._normalize(field, values.get(field))
        entry["status"] = STATUS_ORDER[0]
        entry["计划状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """保存编排修改：校验通过后写回同一份数据，看板与列表读到的就是新值。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        merged = dict(entry)
        for field in EDITABLE_FIELDS:
            if field in values:
                merged[field] = values.get(field)
        problems = self._validate_schedule(merged, exclude_id=entry_id)
        if problems:
            return None, "；".join(problems)
        for field in EDITABLE_FIELDS:
            if field in values:
                entry[field] = self._normalize(field, values.get(field))
        entry["计划状态"] = str(entry.get("status") or STATUS_ORDER[0])
        return entry, "泊位计划编排已保存"

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
            problems = self._validate_schedule(entry, exclude_id=entry_id)
            if problems:
                return None, "；".join(problems)
        entry["status"] = target
        entry["计划状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"泊位计划已{action}"

    def _validate_schedule(self, values: dict[str, Any], exclude_id: int | None = None) -> list[str]:
        """编排校验：登记、修改、确认编排共用同一条规则，通过后才允许落库。"""
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
        start = _parse_time(values.get("计划靠泊时间"))
        end = _parse_time(values.get("计划离泊时间"))
        if start is None:
            problems.append("计划靠泊时间缺失或格式无法识别（示例：2026-09-25 08:00）")
        if end is None:
            problems.append("计划离泊时间缺失或格式无法识别（示例：2026-09-26 20:00）")
        if start is not None and end is not None:
            if start >= end:
                problems.append("计划靠泊时间必须早于计划离泊时间")
            else:
                conflict = self._find_conflict(
                    str(values.get("泊位编号") or "").strip(), start, end, exclude_id=exclude_id
                )
                if conflict is not None:
                    problems.append(conflict)
        return problems

    def _find_conflict(
        self, berth: str, start: datetime, end: datetime, exclude_id: int | None = None
    ) -> str | None:
        """同一泊位上时间窗口重叠且未离泊的计划即冲突；返回可读的冲突说明。"""
        if not berth:
            return None
        for row in store.rows(MODULE):
            if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
                continue
            if row.get("status") == STATUS_ORDER[-1]:
                continue  # 已离泊的计划不再占用泊位
            if str(row.get("泊位编号") or "").strip() != berth:
                continue
            window = _window_of(row)
            if window is None:
                continue
            other_start, other_end = window
            if start < other_end and other_start < end:
                return (
                    f"泊位「{berth}」{_format_time(other_start)}~{_format_time(other_end)} "
                    f"已被计划「{row.get('计划编号')}」（{row.get('靠泊船舶')}）占用，请错开时间或更换泊位"
                )
        return None

    @staticmethod
    def _normalize(field: str, value: Any) -> str:
        text = str(value or "").strip()
        if field in ("计划靠泊时间", "计划离泊时间"):
            parsed = _parse_time(text)
            if parsed is not None:
                return _format_time(parsed)
        return text
