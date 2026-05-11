#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步追踪代码文件（tracked_codes.txt）

用途：
1. 扫描 analysis-reports/*_投资分析报告.md
2. 提取港股5位代码，写入 07-标的追踪/tracked_codes.txt
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "analysis-reports"
OUT_FILE = ROOT / "07-标的追踪" / "tracked_codes.txt"


def collect_codes() -> list[str]:
    pattern = re.compile(r"_(\d{5})_投资分析报告\.md$")
    codes: set[str] = set()
    for file in REPORT_DIR.glob("*_投资分析报告.md"):
        m = pattern.search(file.name)
        if m:
            codes.add(f"{m.group(1)}.HK")
    return sorted(codes)


def main() -> int:
    codes = collect_codes()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# 自动生成，请勿手动编辑",
        f"# 更新时间: {now}",
        f"# 总数: {len(codes)}",
        "",
    ]
    lines.extend(codes)
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[OK] 已写入 {OUT_FILE} ({len(codes)} 个代码)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
