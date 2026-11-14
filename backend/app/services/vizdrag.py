"""拖拽可视化业务规则：状态流转、字段绑定准入、校验结论缓存与并发版本控制。

字段绑定准入的唯一标准集中在本模块：
- 同一数据源下，横轴/纵轴/分组字段只能取该数据源允许范围内的字段；
- 横纵轴条件互相冲突（同一字段落到多个位置）时，按唯一优先级
  「纵轴字段 > 横轴字段 > 分组字段」裁决，冲突直接拒绝保存/发布；
- 各位置有明确上限，超过上限不允许保存；
- 发布走完整准入（必填 + 范围 + 上限 + 冲突），草稿保存只校验已提交的绑定。
"""
from __future__ import annotations

import json
import threading
from typing import Any

from app.store import store

MODULE = "vizdrag"
REQUIRED_FIELDS = ["方案编号", "方案名称", "数据源绑定"]
BINDING_FIELDS = ["数据源绑定", "图表类型", "横轴字段", "纵轴字段", "分组字段"]
STATUS_ORDER = ["草稿", "已发布", "已嵌入", "已归档"]

# 动作 -> (要求的源状态, 目标状态)；源状态不匹配时拒绝执行
ACTION_RULES: dict[str, tuple[str, str]] = {
    "发布方案": ("草稿", "已发布"),
    "嵌入看板": ("已发布", "已嵌入"),
    "归档方案": ("已嵌入", "已归档"),
}
NEGATIVE_ACTIONS: list[str] = []

# 各绑定位置的字段数量上限
X_AXIS_LIMIT = 1
Y_AXIS_LIMIT = 1
GROUP_LIMIT = 2
TOTAL_BINDING_LIMIT = 4

# 位置冲突时的唯一优先级：位次越小优先级越高
SLOT_PRIORITY = ["纵轴字段", "横轴字段", "分组字段"]
PRIORITY_TEXT = "纵轴字段 > 横轴字段 > 分组字段"

# 同一数据源下的字段允许范围与图表类型白名单
DATASOURCE_SCHEMA: dict[str, dict[str, Any]] = {
    "销售明细数据仓库": {
        # 横轴允许范围（维度字段）
        "dimensions": ["日期", "地区", "渠道", "品类"],
        # 纵轴允许范围（度量字段）
        "measures": ["销售额", "订单量", "客单价"],
        # 分组允许范围
        "groups": ["region", "channel", "日期", "地区", "渠道", "品类"],
        "chart_types": ["柱状图", "折线图", "饼图"],
    },
}

# 各位置对应的允许范围键名
SLOT_POOL_KEY = {
    "横轴字段": "dimensions",
    "纵轴字段": "measures",
    "分组字段": "groups",
}
SLOT_LIMITS = {
    "横轴字段": X_AXIS_LIMIT,
    "纵轴字段": Y_AXIS_LIMIT,
    "分组字段": GROUP_LIMIT,
}


def _as_field_list(value: Any) -> list[str]:
    """把字符串（逗号/分号分隔）或数组形式的绑定值统一成去空白后的字段列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).replace("，", ",").replace("；", ",").replace(";", ",").split(",")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _binding_fingerprint(values: dict[str, Any]) -> str:
    """绑定内容指纹：同一方案编号、同一份绑定内容必然得到同一个指纹。"""
    snapshot = {field: values.get(field) for field in BINDING_FIELDS}
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)


class VizdragService:
    def __init__(self) -> None:
        # 同一方案编号只保留一份校验结论：方案编号 -> (绑定指纹, 结论)
        self._validate_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        # 绑定写入串行化，保证两个编辑者并发修改时只有先通过校验的版本落库
        self._lock = threading.RLock()
        # 延迟导入，避免与分析导出中心服务形成模块级循环导入
        from app.services.export import ExportService

        self._export_service = ExportService()

    # ------------------------------------------------------------------ 查询
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
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def binding_rules(self) -> dict[str, Any]:
        """对外暴露字段绑定准入的唯一标准，供前端按允许范围渲染候选项。"""
        return {
            "datasources": DATASOURCE_SCHEMA,
            "limits": SLOT_LIMITS | {"绑定字段总数": TOTAL_BINDING_LIMIT},
            "slot_priority": SLOT_PRIORITY,
            "priority_text": PRIORITY_TEXT,
        }

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        code = str(values.get("方案编号") or "").strip()
        if any(str(row.get("方案编号") or "").strip() == code for row in rows):
            return None, [f"方案编号 {code} 已存在，同一方案编号只允许登记一份"]
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in BINDING_FIELDS:
            if field in REQUIRED_FIELDS:
                continue
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["binding_version"] = 1
        rows.append(entry)
        return entry, []

    # ---------------------------------------------------------- 字段绑定准入
    def _slot_bindings(self, values: dict[str, Any]) -> dict[str, list[str]]:
        return {slot: _as_field_list(values.get(slot)) for slot in SLOT_PRIORITY}

    def _check_binding(
        self,
        values: dict[str, Any],
        *,
        full_admission: bool,
    ) -> list[str]:
        """字段绑定准入核心。full_admission=True 用于发布（缺失必填也拒绝）。

        校验顺序固定，保证同一份绑定内容永远得到同一份结论：
        数据源 -> 图表类型 -> 各位置允许范围 -> 位置内重复 -> 数量上限 ->
        跨位置冲突（唯一优先级）-> 绑定总数上限。
        """
        errors: list[str] = []
        datasource = str(values.get("数据源绑定") or "").strip()
        if not datasource:
            # 数据源是所有字段允许范围的前提，草稿与发布都不允许缺失
            errors.append("缺少数据源绑定，字段绑定必须挂在已登记的数据源下")
            return errors
        schema = DATASOURCE_SCHEMA.get(datasource)
        if schema is None:
            errors.append(f"数据源「{datasource}」未登记字段允许范围，不允许绑定字段")
            return errors

        chart_type = str(values.get("图表类型") or "").strip()
        if full_admission and not chart_type:
            errors.append("缺少图表类型，发布前必须选择图表类型")
        elif chart_type and chart_type not in schema["chart_types"]:
            allowed = "、".join(schema["chart_types"])
            errors.append(f"图表类型「{chart_type}」不在数据源「{datasource}」允许范围内（允许：{allowed}）")

        slots = self._slot_bindings(values)

        # 发布准入：横轴、纵轴为必填；分组按图表需要可选
        if full_admission:
            if not slots["横轴字段"]:
                errors.append("缺少横轴字段，发布前必须绑定横轴")
            if not slots["纵轴字段"]:
                errors.append("缺少纵轴字段，发布前必须绑定纵轴")

        owner: dict[str, str] = {}
        total_count = 0
        for slot in SLOT_PRIORITY:
            fields = slots[slot]
            total_count += len(fields)
            pool = schema[SLOT_POOL_KEY[slot]]
            for field in fields:
                if field not in pool:
                    allowed = "、".join(pool)
                    errors.append(
                        f"{slot}「{field}」不在数据源「{datasource}」的允许范围内（允许：{allowed}）"
                    )
            # 同一位置内不允许重复绑定（重复分组在这里被拦下）
            duplicated = sorted({field for field in fields if fields.count(field) > 1})
            for field in duplicated:
                errors.append(f"{slot}「{field}」重复绑定，同一位置只允许保留一份")
            # 数量上限
            limit = SLOT_LIMITS[slot]
            if len(fields) > limit:
                errors.append(f"{slot}绑定了 {len(fields)} 个字段，超过上限 {limit} 个，不允许保存")

        # 跨位置冲突：同一字段落到多个位置时，按唯一优先级裁决并拒绝，避免静默改写用户数据
        for slot in SLOT_PRIORITY:
            for field in slots[slot]:
                if field in owner:
                    errors.append(
                        f"字段「{field}」同时绑定到{owner[field]}与{slot}，"
                        f"按唯一优先级（{PRIORITY_TEXT}）只能保留高优先级位置，请删除低优先级绑定"
                    )
                else:
                    owner[field] = slot

        if total_count > TOTAL_BINDING_LIMIT:
            errors.append(
                f"绑定字段总数 {total_count} 个，超过允许上限 {TOTAL_BINDING_LIMIT} 个，不允许保存"
            )
        return errors

    def validate_entry(
        self,
        entry_id: int,
        *,
        override: dict[str, Any] | None = None,
        full_admission: bool = True,
        force: bool = False,
    ) -> dict[str, Any] | None:
        """对单条方案做字段绑定准入校验。

        同一方案编号 + 同一份绑定内容只保留一份结论（命中缓存直接返回），
        绑定内容变化后旧结论自动失效；override 仅用于保存前的临时校验，不写缓存。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        values = dict(entry)
        if override:
            values.update(override)
        fingerprint = _binding_fingerprint(values)
        code = str(entry.get("方案编号") or "")

        with self._lock:
            if override is None and not force:
                cached = self._validate_cache.get(code)
                if cached and cached[0] == fingerprint:
                    conclusion = dict(cached[1])
                    conclusion["cached"] = True
                    return conclusion

            errors = self._check_binding(values, full_admission=full_admission)
            conclusion = {
                "ok": not errors,
                "方案编号": code,
                "binding_version": entry.get("binding_version", 1),
                "fingerprint": fingerprint,
                "errors": errors,
                "conclusion": "校验通过" if not errors else "校验不通过：" + "；".join(errors),
                "cached": False,
            }
            if override is None:
                # 同一方案编号始终只保留最新一份结论
                self._validate_cache[code] = (fingerprint, conclusion)
            return conclusion

    # ------------------------------------------------------------- 绑定保存
    def save_binding(
        self,
        entry_id: int,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """保存字段绑定（草稿可部分保存）。

        带乐观版本号：两个编辑者同时修改时，expected_version 与当前版本一致、
        且先通过条件校验的版本才允许落库；后到者被拒绝并提示刷新。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"可视化方案 {entry_id} 不存在或已归档"

        expected_version = values.get("expected_version")
        with self._lock:
            current_version = int(entry.get("binding_version", 1))
            if expected_version is not None and int(expected_version) != current_version:
                return (
                    None,
                    f"方案绑定已被其他编辑者更新（当前版本 {current_version}），"
                    "请刷新后重新提交，后提交的版本不覆盖先通过条件校验的版本",
                )

            # 显式提交即更新：空字符串/空数组表示清空该位置绑定；未提交的字段保持原值
            merged = dict(entry)
            for field in BINDING_FIELDS:
                if field in values and values.get(field) is not None:
                    merged[field] = values.get(field)

            # 草稿阶段做准入校验（缺失必填不拦，但范围/重复/上限/冲突一律拦）
            errors = self._check_binding(merged, full_admission=False)
            if errors:
                return None, "字段绑定未通过准入：" + "；".join(errors)

            for field in BINDING_FIELDS:
                if field in values and values.get(field) is not None:
                    entry[field] = values.get(field)
            entry["binding_version"] = current_version + 1
            # 绑定内容已变，旧校验结论立即失效
            self._validate_cache.pop(str(entry.get("方案编号") or ""), None)
            return entry, f"字段绑定已保存，绑定版本更新为 {entry['binding_version']}"

    # ---------------------------------------------------------------- 动作
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"可视化方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于拖拽可视化可执行范围"
        source_status, target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry.get("status") != source_status:
            return None, f"当前状态为「{entry.get('status')}」，动作「{action}」只允许在「{source_status}」状态执行"

        if action == "发布方案":
            # 发布走完整字段绑定准入；任何一项不过都不允许发布
            conclusion = self.validate_entry(entry_id, full_admission=True)
            if conclusion is None:
                return None, f"可视化方案 {entry_id} 不存在或已归档"
            if not conclusion["ok"]:
                return None, "发布被拒绝：" + conclusion["conclusion"]

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS

        message = f"可视化方案已{action}"
        if action == "发布方案":
            # 发布结果同步到分析导出中心，并按字段规则验收
            synced = self._export_service.sync_published_scheme(entry)
            message += f"，已同步分析导出中心（{synced['任务编号']}，{synced['验收结论']}）"
        elif action == "归档方案":
            self._export_service.expire_synced_scheme(entry)
            message += "，分析导出中心中的同步任务已置为已过期"
        return entry, message
