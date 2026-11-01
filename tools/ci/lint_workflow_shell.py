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

# `$NAME` 紧跟一个非 ASCII 字符 —— bash -n 抓不到，但它在运行时一定错。
#
# 由来：nested-boot 的 space job 写了 `echo "退出码 = $rc（1 = 没腾到目标）"`，
# 运行器上报 `rc（: unbound variable` 然后整步失败。UTF-8 locale 下的 bash 把
# 全角括号当成了标识符字符，于是变量名被读成 `rc（`。
#
# 本项目所有注释与提示都是中文，这个形状随手就会写出来，而代价是一次
# CI 往返（macOS runner 一轮几十分钟）。没有 set -u 的步骤里它更坏：
# 不报错，静默展开成空串，于是日志里的数字是错的而没人知道。
# 正确写法一律是 `${rc}`。
# 前面的 (?<!\\) 是为了放过 `\$RAW` 这种转义写法：它原样打印一个美元号，
# 不展开，所以紧跟全角字符没有任何问题。
VAR_THEN_WIDE = re.compile(r"(?<!\\)\$([A-Za-z_][A-Za-z0-9_]*)([^\x00-\x7f])")

# 整行注释里的 `$VAR（` 也不展开。只放过「整行注释」这一种：行内 `#` 之后的
# 注释要准确判断得先知道引号状态，不值得为它写一个 shell 词法分析器 ——
# 而且那种情况下改成 ${VAR} 本来也无害。
COMMENT_LINE = re.compile(r"^\s*#")


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

    total = bad = wide = 0
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
            hits = []
            for lineno, line in enumerate(script.splitlines(), 1):
                if COMMENT_LINE.match(line):
                    continue
                for m in VAR_THEN_WIDE.finditer(line):
                    hits.append((lineno, m.group(1), m.group(2), line.strip()))

            if proc.returncode == 0 and not hits:
                print(f"  [√] {job} / 步 {idx}  {name}")
                continue

            print(f"  [×] {job} / 步 {idx}  {name}")
            if proc.returncode != 0:
                bad += 1
                for line in (proc.stdout + proc.stderr).splitlines():
                    print(f"        {line}")
            for lineno, var, ch, text in hits:
                wide += 1
                print(
                    f"        第 {lineno} 行  ${var} 后面紧跟 {ch!r} "
                    f"→ bash 会把变量名读成 `{var}{ch}`，改写成 ${{{var}}}"
                )
                print(f"          {text}")

    print(f"\n{total} 个 run 块，{bad} 个有语法错，{wide} 处 $变量紧跟全角字符")
    return 1 if (bad or wide) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
