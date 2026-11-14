"""分析导出中心业务规则：状态流转、字段校验、可视化方案发布结果同步与验收。"""
from __future__ import annotations

import threading
from typing import Any

from app.services.vizdrag import (
    GROUP_LIMIT,
    TOTAL_BINDING_LIMIT,
    X_AXIS_LIMIT,
    Y_AXIS_LIMIT,
    _as_field_list,
)
from app.store import store

MODULE = "export"
REQUIRED_FIELDS = ["任务编号", "数据源名称", "导出格式"]
STATUS_ORDER = ["草稿", "导出中", "已完成", "已过期"]
ACTION_RULES = {"开始导出": "草稿", "标记完成": "导出中", "清理文件": "已完成"}
NEGATIVE_ACTIONS = []

# 分析导出中心自身的字段规则验收上限
EXPORT_FIELD_LIMIT = TOTAL_BINDING_LIMIT
EXPORT_ROW_LIMIT = 100_000
SYNC_TASK_PREFIX = "EXPO-VIZD-"
SYNC_SOURCE = "拖拽可视化方案发布"


class ExportService:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"导出任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分析导出中心可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"导出任务已{action}"

    # ---------------------------------------------- 可视化方案发布结果同步与验收
    def _synced_task_code(self, scheme: dict[str, Any]) -> str:
        return f"{SYNC_TASK_PREFIX}{scheme.get('方案编号')}"

    def _acceptance_check(self, scheme: dict[str, Any]) -> tuple[str, str]:
        """分析导出中心按字段规则验收同步过来的方案绑定。

        验收口径与拖拽可视化的允许范围/上限保持一致；返回 (结论, 明细)。
        """
        x_fields = _as_field_list(scheme.get("横轴字段"))
        y_fields = _as_field_list(scheme.get("纵轴字段"))
        g_fields = _as_field_list(scheme.get("分组字段"))
        total = len(x_fields) + len(y_fields) + len(g_fields)
        details: list[str] = []

        if len(x_fields) > X_AXIS_LIMIT:
            details.append(f"横轴字段 {len(x_fields)} 个，超过上限 {X_AXIS_LIMIT}")
        if len(y_fields) > Y_AXIS_LIMIT:
            details.append(f"纵轴字段 {len(y_fields)} 个，超过上限 {Y_AXIS_LIMIT}")
        if len(g_fields) > GROUP_LIMIT:
            details.append(f"分组字段 {len(g_fields)} 个，超过上限 {GROUP_LIMIT}")
        if total > EXPORT_FIELD_LIMIT:
            details.append(f"字段选择 {total} 个，超过导出字段上限 {EXPORT_FIELD_LIMIT}")

        upper = scheme.get("导出上限")
        row_limit: int
        if str(upper or "").strip().isdigit():
            row_limit = int(upper)
        else:
            row_limit = EXPORT_ROW_LIMIT
        if row_limit > EXPORT_ROW_LIMIT:
            details.append(f"导出上限 {row_limit} 行，超过允许上限 {EXPORT_ROW_LIMIT} 行")

        if details:
            return "验收不通过", "；".join(details)
        return "验收通过", f"字段选择 {total} 个、导出上限 {row_limit} 行，均在允许范围内"

    def sync_published_scheme(self, scheme: dict[str, Any]) -> dict[str, Any]:
        """把已发布的可视化方案同步成一条导出任务。

        同一方案编号只保留一份导出任务（按任务编号幂等 upsert），
        重复同步不会产生重复任务，只刷新绑定内容与验收结论。
        """
        task_code = self._synced_task_code(scheme)
        x_fields = _as_field_list(scheme.get("横轴字段"))
        y_fields = _as_field_list(scheme.get("纵轴字段"))
        g_fields = _as_field_list(scheme.get("分组字段"))
        field_selection = "、".join(x_fields + y_fields + g_fields)
        acceptance, acceptance_detail = self._acceptance_check(scheme)

        with self._lock:
            rows = store.rows(MODULE)
            existing = next((row for row in rows if row.get("任务编号") == task_code), None)
            if existing is not None:
                existing.update({
                    "数据源名称": scheme.get("数据源绑定"),
                    "字段选择": field_selection,
                    "筛选条件": f"图表类型={scheme.get('图表类型') or '未指定'}",
                    "导出上限": str(EXPORT_ROW_LIMIT),
                    "关联方案编号": scheme.get("方案编号"),
                    "同步来源": SYNC_SOURCE,
                    "绑定版本": scheme.get("binding_version", 1),
                    "验收结论": acceptance,
                    "验收明细": acceptance_detail,
                    "任务状态": "已完成" if acceptance == "验收通过" else "草稿",
                })
                existing["status"] = existing["任务状态"]
                existing["pending"] = existing["status"] != STATUS_ORDER[-1]
                existing["abnormal"] = acceptance != "验收通过"
                return existing

            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({
                "任务编号": task_code,
                "数据源名称": scheme.get("数据源绑定"),
                "导出格式": "CSV",
                "字段选择": field_selection,
                "筛选条件": f"图表类型={scheme.get('图表类型') or '未指定'}",
                "导出上限": str(EXPORT_ROW_LIMIT),
                "文件大小": "待生成",
                "任务状态": "已完成" if acceptance == "验收通过" else "草稿",
                "关联方案编号": scheme.get("方案编号"),
                "同步来源": SYNC_SOURCE,
                "绑定版本": scheme.get("binding_version", 1),
                "验收结论": acceptance,
                "验收明细": acceptance_detail,
            })
            entry["status"] = entry["任务状态"]
            entry["pending"] = entry["status"] != STATUS_ORDER[-1]
            entry["abnormal"] = acceptance != "验收通过"
            rows.append(entry)
            return entry

    def expire_synced_scheme(self, scheme: dict[str, Any]) -> dict[str, Any] | None:
        """方案归档时，把分析导出中心里对应的同步任务置为已过期。"""
        task_code = self._synced_task_code(scheme)
        with self._lock:
            existing = next(
                (row for row in store.rows(MODULE) if row.get("任务编号") == task_code),
                None,
            )
            if existing is None:
                return None
            existing["status"] = "已过期"
            existing["任务状态"] = "已过期"
            existing["pending"] = False
            return existing

    def sync_published_schemes(self) -> list[dict[str, Any]]:
        """全量补偿同步：把所有已发布/已嵌入的方案重新同步一遍，仍按方案编号幂等。"""
        from app.services.vizdrag import MODULE as VIZ_MODULE

        schemes = [
            row for row in store.rows(VIZ_MODULE)
            if row.get("status") in ("已发布", "已嵌入")
        ]
        return [self.sync_published_scheme(scheme) for scheme in schemes]
