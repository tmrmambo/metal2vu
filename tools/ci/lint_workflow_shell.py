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

# GitHub Actions 跑 run 块用的是 `bash -e {0}` —— **errexit 默认就是开着的**。
# 于是 `set -uo pipefail` 这个写法是个陷阱：看起来像在设置选项，实际上对 errexit
# 一个字也没说，而它开着。一条返回非零的诊断命令（ls 撞上 Permission denied、
# grep 没匹配到、find 碰上一个读不了的目录）就会把整步掐掉，末尾那句 exit 0
# 根本执行不到，于是「跑了但被挡」和「没跑」在日志里分不开。
#
# 由来：installer-source 的「Preboot 里的 restore 目录」那步死在
# `ls: /System/Volumes/Preboot/com.apple.security.cryptexd/: Permission denied`，
# 而它要找的 BuildManifest.plist 其实已经打印出来了 —— 结论拿到了，步骤却是红的。
#
# 所以要求把意图写明白，两种之一：
#     set -euo pipefail       严格：任何一条命令失败就停（真要做事的步骤）
#     set +e -u -o pipefail   诊断：容错往下跑，末尾 exit 0 决定退出码
#
# 规则只盯「在谈错误处理」的那些 set 行（提到 u 或 pipefail 的）。`set -x` 只是
# 开命令回显，跟 errexit 无关，不该被拖进来。
SET_LINE = re.compile(r"^\s*set\s+([-+].*?)\s*$")


def set_line_facts(flags: str) -> tuple[str, bool]:
    """返回 (短选项字母, 是否提到 pipefail)。

    `set -uo pipefail` 里的 `pipefail` 是 `-o` 的参数，不是独立选项；
    `set +e -u -o pipefail` 里三段分开写。两种都要认。
    """
    letters = ""
    tokens = flags.split()
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith(("-", "+")):
            body = tok[1:]
            letters += body
            if body.endswith("o"):  # -o / -uo 之后跟的是选项名
                skip_next = True
    return letters, "pipefail" in tokens


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

    total = bad = wide = vague = 0
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
            set_lines: list[tuple[int, str]] = []
            for lineno, line in enumerate(script.splitlines(), 1):
                if COMMENT_LINE.match(line):
                    continue
                for m in VAR_THEN_WIDE.finditer(line):
                    hits.append((lineno, m.group(1), m.group(2), line.strip()))
                m = SET_LINE.match(line)
                if m:
                    set_lines.append((lineno, m.group(1)))

            # errexit 的意图说清楚了没有：任何一条 set 行提到 e（-e 或 +e）就算说清了
            facts = [(ln, f, *set_line_facts(f)) for ln, f in set_lines]
            says_e = any("e" in letters for _, _, letters, _ in facts)
            ambiguous = [
                (ln, f)
                for ln, f, letters, pipefail in facts
                if not says_e and ("u" in letters or pipefail)
            ]

            if proc.returncode == 0 and not hits and not ambiguous:
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
            for lineno, flags in ambiguous:
                vague += 1
                print(
                    f"        第 {lineno} 行  `set {flags}` 没说 errexit —— "
                    f"而 GitHub 用 bash -e，它默认开着"
                )
                print("          严格步骤写 set -euo pipefail；诊断步骤写 set +e -u -o pipefail")

    print(
        f"\n{total} 个 run 块，{bad} 个有语法错，"
        f"{wide} 处 $变量紧跟全角字符，{vague} 处 set 没表态 errexit"
    )
    return 1 if (bad or wide or vague) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
