#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印一次 GitHub Actions run 的逐步骤结果。

PowerShell 里给 `gh ... --jq` 传含引号的表达式很容易被壳层吃掉，所以把
格式化挪到脚本里。

用法：
  py tools/ci/runstat.py            # 最近 6 次 run 概览
  py tools/ci/runstat.py <run-id>   # 某次 run 的逐步骤
"""
import json
import subprocess
import sys


def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stdout


def overview(n: int = 6) -> None:
    out = gh(["run", "list", "--limit", str(n), "--json",
              "databaseId,workflowName,status,conclusion,createdAt"])
    for r in json.loads(out or "[]"):
        print(f"{r['databaseId']}  {r['workflowName']:26} "
              f"{r['status']}/{r['conclusion'] or '-':10} {r['createdAt']}")


def detail(run_id: str) -> None:
    out = gh(["run", "view", run_id, "--json", "conclusion,displayTitle,jobs"])
    d = json.loads(out or "{}")
    if not d:
        print(f"no data for run {run_id}")
        return
    print(f"run {run_id}: {d.get('displayTitle', '')}")
    print(f"conclusion: {d.get('conclusion')}\n")
    for j in d.get("jobs", []):
        print(f"=== {j['name']}: {j['status']}/{j.get('conclusion') or '-'}")
        for s in j.get("steps", []):
            mark = {"success": "ok  ", "failure": "FAIL", "skipped": "skip",
                    "cancelled": "canc"}.get(s.get("conclusion") or "", "... ")
            print(f"  [{mark}] {s['name']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        detail(sys.argv[1])
    else:
        overview()
