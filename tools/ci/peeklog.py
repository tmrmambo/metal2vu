#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 GitHub Actions 的 job 日志里只挑出「命令的运行时输出」那些行。

为什么需要它
------------
`gh run view --job <id> --log` 的每一行形如

    <job 名>\t<步骤名>\t<ISO 时间戳> <内容>

而 `##[group]Run …` 之后那一大段是**步骤脚本源码的回显**，每行被包在 ANSI 的
`ESC[36;1m … ESC[0m` 里。本项目的 workflow 里内嵌了几百行 bash，于是一个步骤的
日志里源码回显比真实输出多出一个数量级，肉眼翻不过来。本脚本把回显去掉。

编码这件事必须自己处理：在 Windows 上 `gh … > file.log` 很容易写成 UTF-16LE，
按 UTF-8 读会把每个 ASCII 字符后面的 NUL 读成替换字符，连 ANSI 序列都认不出来
（这个坑本项目踩过一次，表现是「过滤器完全不生效」）。所以这里按 BOM 与 NUL
密度嗅探，而不是假定 UTF-8。

在 PowerShell 上取日志**必须先把控制台编码设成 UTF-8**，否则 PowerShell 会用
控制台代码页（cp437/cp850）去读 `gh` 的 UTF-8 输出、把中文搞坏、再按 UTF-8 写回文件，
于是文件里是双重破坏过的文本，而 ESC 也被写成了字面的两个字符 `^` `[`：

    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    gh run view --job <id> --log > j.log

本脚本对两种形态都认：真 ESC（`\\x1b[36;1m`）与字面的 `^[[36;1m`。

用法
----
    python3 tools/ci/peeklog.py j.log                      # 全部运行时输出
    python3 tools/ci/peeklog.py j.log V-020                # 只看步骤名含 V-020 的
    python3 tools/ci/peeklog.py j.log V-020 护栏 FATAL     # 再按内容关键字过滤
"""
from __future__ import annotations

import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

# 真 ESC 与字面 `^[` 两种写法都要认（见上面关于 PowerShell 的那一段）
ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*[A-Za-z]")
LINE = re.compile(r"^(.*?)\t(.*?)\t(\d{4}-\d\d-\d\dT[\d:.]+Z) ?(.*)$")


def read_text(path: str) -> str:
    """按 BOM 与 NUL 密度嗅探编码。gh 在 Windows 上常写出 UTF-16LE。"""
    raw = open(path, "rb").read()
    for bom, enc in (
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
        (b"\xef\xbb\xbf", "utf-8-sig"),
    ):
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace")
    head = raw[:4096]
    if head.count(b"\x00") > len(head) // 4:
        # 没有 BOM 但 NUL 很密 —— 看 NUL 落在偶数位还是奇数位来定端序
        even = sum(1 for i in range(0, len(head), 2) if head[i : i + 1] == b"\x00")
        enc = "utf-16-be" if even * 2 > head.count(b"\x00") else "utf-16-le"
        return raw.decode(enc, errors="replace")
    return raw.decode("utf-8", errors="replace")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = argv[1]
    step_kw = argv[2] if len(argv) > 2 else ""
    needles = argv[3:]

    kept = skipped = 0
    for line in read_text(path).splitlines():
        line = line.lstrip("\ufeff")
        m = LINE.match(line)
        if not m:
            continue
        _job, step, _ts, body = m.groups()
        if step_kw and step_kw not in step:
            continue
        if ANSI.search(body) or body.startswith(("##[group]", "##[endgroup]")):
            skipped += 1  # 脚本源码的回显或分组标记
            continue
        body = ANSI.sub("", body)
        if needles and not any(n in body for n in needles):
            continue
        kept += 1
        print(body)

    print(f"\n[peeklog] 输出 {kept} 行，过滤掉 {skipped} 行源码回显", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
