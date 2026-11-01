#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 workflow 里每个 `run:` 块跑一遍 `bash -n`（只做语法检查，不执行）。

动机：forensics-boot-layout.yml 的 `tooling` job 里有几百行内嵌 bash。
一个括号配错就是一次 CI 往返（macOS runner 上一轮 45 分钟）。
本脚本在本地就把语法错挑出来。

GitHub Actions 的 `${{ ... }}` 表达式在 bash 看来不是合法语法，
所以先把它们替换成一个占位字符串再检查。

用法:
    python3 tools/ci/lint_workflow_shell.py [.github/workflows/*.yml ...]
不给参数就检查 .github/workflows 下所有 .yml。

需要 PATH 里有 bash。Windows 上会自动找 Git for Windows 带的那个。
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

EXPR = re.compile(r"\$\{\{[^}]*\}\}")


def find_bash() -> str | None:
    found = shutil.which("bash")
    if found:
        return found
    for cand in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.exists(cand):
            return cand
    return None


def iter_runs(doc: dict):
    """产出 (job 名, 步骤序号, 步骤名, run 脚本)。"""
    for job_name, job in (doc.get("jobs") or {}).items():
        for i, step in enumerate(job.get("steps") or [], 1):
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield job_name, i, step.get("name") or "(无名)", step["run"]


def main(argv: list[str]) -> int:
    bash = find_bash()
    if not bash:
        print("找不到 bash，跳过检查（退出码 0，不阻塞）")
        return 0

    paths = argv[1:] or sorted(glob.glob(".github/workflows/*.yml"))
    if not paths:
        print("没有找到要检查的 workflow")
        return 1

    total = bad = 0
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if not isinstance(doc, dict):
            continue
        print(f"\n=== {path} ===")
        for job, idx, name, script in iter_runs(doc):
            total += 1
            # ${{ }} → 占位。用一个不含特殊字符的词，免得自己制造语法错。
            cleaned = EXPR.sub("GHA_EXPR_PLACEHOLDER", script)
            with tempfile.NamedTemporaryFile(
                "w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
            ) as tf:
                tf.write("#!/usr/bin/env bash\n")
                tf.write(cleaned)
                tmp = tf.name
            try:
                proc = subprocess.run(
                    [bash, "-n", tmp], capture_output=True, text=True, timeout=60
                )
            finally:
                os.unlink(tmp)
            if proc.returncode == 0:
                print(f"  [√] {job} / 步 {idx}  {name}")
            else:
                bad += 1
                print(f"  [×] {job} / 步 {idx}  {name}")
                for line in (proc.stdout + proc.stderr).splitlines():
                    print(f"        {line}")

    print(f"\n{total} 个 run 块，{bad} 个有语法错")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
