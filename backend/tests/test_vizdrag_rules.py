"""字段绑定准入与发布同步验收脚本（纯标准库，python tests/test_vizdrag_rules.py 直接运行）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.export import ExportService, MODULE as EXPORT_MODULE
from app.services.vizdrag import VizdragService, MODULE as VIZ_MODULE
from app.store import store

viz = VizdragService()
export = ExportService()
passed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")
        raise SystemExit(f"验收失败：{name} {detail}")


def find_code(code: str) -> dict:
    return next(row for row in store.rows(VIZ_MODULE) if row["方案编号"] == code)


print("1) 种子数据固定绑定")
s1, s2, s3 = find_code("VIZD-0001"), find_code("VIZD-0002"), find_code("VIZD-0003")
check("VIZD-0001 分组字段为 region", s1["分组字段"] == "region")
check("VIZD-0003 分组字段为 channel", s3["分组字段"] == "channel")
check("0001 与 0003 横轴不共享默认绑定", s1["横轴字段"] != s3["横轴字段"],
      f"{s1['横轴字段']} vs {s3['横轴字段']}")

print("2) VIZD-0002 日期/销售额/渠道允许发布，缺纵轴拒绝")
r = viz.validate_entry(s2["id"], full_admission=True)
check("完整绑定校验通过", r["ok"] is True, r["conclusion"])
r = viz.validate_entry(s2["id"], override={"纵轴字段": ""}, full_admission=True)
check("缺少纵轴发布被拒", r["ok"] is False and any("纵轴" in e for e in r["errors"]), str(r))
r = viz.validate_entry(s2["id"], override={"横轴字段": ""}, full_admission=True)
check("缺少横轴发布被拒", r["ok"] is False and any("横轴" in e for e in r["errors"]), str(r))
r = viz.validate_entry(s2["id"], override={"图表类型": ""}, full_admission=True)
check("缺少图表类型发布被拒", r["ok"] is False, str(r))

print("3) 同一数据源下按允许范围校验")
entry, msg = viz.save_binding(s1["id"], {"横轴字段": "不存在的字段"})
check("范围外字段不允许保存", entry is None and "允许范围" in msg, msg)
entry, msg = viz.save_binding(s1["id"], {"图表类型": "雷达图"})
check("范围外图表类型不允许保存", entry is None and "图表类型" in msg, msg)
entry, msg = viz.save_binding(s1["id"], {"数据源绑定": "未登记数据源"})
check("未登记数据源不允许绑定", entry is None and "未登记" in msg, msg)
cur_ver = find_code("VIZD-0001")["binding_version"]
entry, msg = viz.save_binding(s1["id"], {"数据源绑定": "", "expected_version": cur_ver})
check("缺失数据源绑定不允许保存", entry is None and "缺少数据源绑定" in msg, msg)

print("4) 重复分组/重复位置绑定拦截")
entry, msg = viz.save_binding(s1["id"], {"分组字段": "region,region"})
check("重复分组不允许保存", entry is None and "重复绑定" in msg, msg)
entry, msg = viz.save_binding(s1["id"], {"纵轴字段": ["销售额", "销售额"]})
check("重复纵轴不允许保存", entry is None and "重复绑定" in msg, msg)

print("5) 超过上限不允许保存")
entry, msg = viz.save_binding(s1["id"], {"分组字段": "region,channel,日期"})
check("分组超过 2 个上限拒绝", entry is None and "上限" in msg, msg)
entry, msg = viz.save_binding(s1["id"], {"纵轴字段": ["销售额", "订单量"]})
check("纵轴超过 1 个上限拒绝", entry is None and "上限" in msg, msg)

print("6) 横纵轴冲突时按唯一优先级裁决")
entry, msg = viz.save_binding(s1["id"], {"横轴字段": "销售额"})
check("横轴占用纵轴字段被拒并提示优先级", entry is None and "纵轴字段 > 横轴字段 > 分组字段" in msg, msg)
entry, msg = viz.save_binding(s1["id"], {"分组字段": "销售额"})
check("分组占用纵轴字段被拒并提示优先级", entry is None and "优先级" in msg, msg)

print("7) 校验结论同一方案编号只保留一份")
first = viz.validate_entry(s1["id"], full_admission=True)
second = viz.validate_entry(s1["id"], full_admission=True)
check("同内容重复校验命中缓存", first["fingerprint"] == second["fingerprint"] and second["cached"] is True)
viz.save_binding(s1["id"], {"分组字段": "channel", "expected_version": s1["binding_version"]})
third = viz.validate_entry(s1["id"], full_admission=True)
check("绑定变更后旧结论失效重新校验", third["cached"] is False and third["ok"] is True)
# 还原
viz.save_binding(s1["id"], {"分组字段": "region", "expected_version": s1["binding_version"] + 1})

print("8) 两个编辑者并发修改，只接受先通过条件校验的版本")
base = find_code("VIZD-0001")
ver = base["binding_version"]
ok1, m1 = viz.save_binding(base["id"], {"分组字段": "channel", "expected_version": ver})
check("先到且通过校验的版本落库", ok1 is not None and ok1["binding_version"] == ver + 1, m1)
ok2, m2 = viz.save_binding(base["id"], {"分组字段": "region", "expected_version": ver})
check("后到的旧版本被拒绝", ok2 is None and "其他编辑者" in m2, m2)
ok3, m3 = viz.save_binding(base["id"], {"分组字段": "region", "expected_version": ver + 1})
check("带新版本号可再次提交", ok3 is not None, m3)
# 先到版本本身不合法时整体拒绝，不产生版本号推进
bad_ver = find_code("VIZD-0001")["binding_version"]
before = store.find(VIZ_MODULE, s1["id"])["binding_version"]
ok4, m4 = viz.save_binding(s1["id"], {"分组字段": "越界字段", "expected_version": before})
check("未通过校验的保存不推进版本", ok4 is None and bad_ver == before, m4)
# 显式清空纵轴：草稿允许保存为空，但发布准入必须再次拦截；还原后版本继续递增
ver0 = find_code("VIZD-0001")["binding_version"]
entry, msg = viz.save_binding(s1["id"], {"纵轴字段": "", "expected_version": ver0})
check("空字符串可清空纵轴绑定", entry is not None and entry.get("纵轴字段") == "", msg)
r = viz.validate_entry(s1["id"], full_admission=True)
check("清空纵轴后发布准入拒绝", r["ok"] is False and any("纵轴" in e for e in r["errors"]))
viz.save_binding(s1["id"], {"纵轴字段": "销售额", "expected_version": ver0 + 1})

print("9) 发布走完整准入并同步分析导出中心，按字段规则验收")
entry, msg = viz.run_action(s2["id"], "发布方案")
check("已发布状态不可重复发布", entry is None and "只允许在" in msg, msg)
entry, msg = viz.run_action(s1["id"], "发布方案")
check("VIZD-0001 发布成功", entry is not None and entry["status"] == "已发布", msg)
check("发布消息包含导出中心同步结果", "EXPO-VIZD-VIZD-0001" in msg and "验收通过" in msg, msg)
task = next((r for r in store.rows(EXPORT_MODULE) if r["任务编号"] == "EXPO-VIZD-VIZD-0001"), None)
check("导出中心生成同步任务且只有一份", task is not None and task["验收结论"] == "验收通过", str(task))
viz.run_action(s1["id"], "嵌入看板")
entry, msg = viz.run_action(s1["id"], "发布方案")
check("嵌入后不能再发布", entry is None)
# 幂等：补偿同步不产生重复任务
tasks_before = [r for r in store.rows(EXPORT_MODULE) if r.get("关联方案编号") == "VIZD-0001"]
export.sync_published_schemes()
tasks_after = [r for r in store.rows(EXPORT_MODULE) if r.get("关联方案编号") == "VIZD-0001"]
check("重复同步同一方案只保留一份任务", len(tasks_before) == len(tasks_after) == 1)

print("10) 方案归档联动导出任务过期")
entry, msg = viz.run_action(s1["id"], "归档方案")
check("归档成功", entry is not None and entry["status"] == "已归档", msg)
task = next(r for r in store.rows(EXPORT_MODULE) if r["任务编号"] == "EXPO-VIZD-VIZD-0001")
check("同步任务置为已过期", task["status"] == "已过期", str(task))

print("11) 导出中心字段规则验收：超上限验收不通过")
oversize = dict(s3)
oversize["分组字段"] = "region,channel,日期"  # 3 个分组，超过 2 个上限
result = export.sync_published_scheme(oversize)
check("超上限方案验收不通过", result["验收结论"] == "验收不通过" and "上限" in result["验收明细"], str(result))

print("12) 方案编号唯一性")
dup, missing = viz.create_entry({"方案编号": "VIZD-0001", "方案名称": "x", "数据源绑定": "销售明细数据仓库"})
check("重复方案编号拒绝登记", dup is None and any("已存在" in m for m in missing), str(missing))

print("13) 缺失数据源绑定不允许发布")
new_one, _ = viz.create_entry({"方案编号": "VIZD-0009", "方案名称": "空绑定方案", "数据源绑定": "销售明细数据仓库"})
entry, msg = viz.run_action(new_one["id"], "发布方案")
check("缺横轴纵轴发布拒绝", entry is None and "发布被拒绝" in msg, msg)

print(f"\n全部 {passed} 项验收通过")
