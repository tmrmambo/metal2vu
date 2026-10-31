#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从运行期 ObjC 转储生成 `MTLDevice` / `MTLDeviceSPI` 的逐方法处置表。

为什么这张表能机械生成
----------------------
`21-OBJC-OBJECT-FAMILY.md` 第 8.2 节明说「`MTLDeviceSPI` 的 507 条不逐条抄
进本文」，所以此前只有分类普查与 28 条交集，没有逐条处置。

`91-RUNTIME-EVIDENCE.md` 的转储给了三个类的完整 IMP 集合：

    _MTLDevice          702 个 IMP   基类
    MTLIOAccelDevice     89 个 IMP   家族节点
    AppleParavirtDevice  71 个 IMP   参考实现

而「必须覆写 vs 可以继承」这个问题（`21` 第 10 节）正是这三个集合的
布尔组合。所以处置列不是人工判断，是从转储推出来的：

    基类有 IMP + APV 不覆写  ->  继承（我们也不用写）
    基类有 IMP + APV 覆写    ->  必须覆写（APV 覆写说明基类答案对半虚拟化
                                 设备不成立）
    基类无 IMP + APV 有       ->  必须实现（没有可继承的答案）
    基类无 IMP + APV 无       ->  协议声明了但谁都没实现 -> optional 则不管，
                                 required 则查 `42` 分册的落点

这四格里只有第四格需要人工，而它恰好是最小的一格。

用法
----
  py tools/ci/gen_device_spi_table.py \
      ci-evidence/objc-dump/objc-dump.json \
      docs/spec/23-DEVICE-SPI-DISPOSITION.md
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

SCHEMA = "metal2vu/device-spi-disposition/1"

# ---------------------------------------------------------------------------
# ObjC type encoding 解码
# ---------------------------------------------------------------------------

PRIM = {
    "c": "char/BOOL", "i": "int", "s": "short", "l": "long", "q": "long long",
    "C": "uchar", "I": "uint", "S": "ushort", "L": "ulong", "Q": "ulong long",
    "f": "float", "d": "double", "B": "bool", "v": "void", "*": "char*",
    "@": "id", "#": "Class", ":": "SEL", "?": "unknown/block",
}


def split_encoding(enc: str) -> list[str]:
    """把 method type encoding 拆成 [返回, self, _cmd, 参数...]。

    跳过偏移数字，正确处理嵌套的 {} () [] 与指针/限定符前缀。
    """
    out: list[str] = []
    i, n = 0, len(enc)
    while i < n:
        if enc[i].isdigit():
            i += 1
            continue
        start = i
        # 限定符与指针前缀
        while i < n and enc[i] in "rnNoORV^":
            i += 1
        if i >= n:
            out.append(enc[start:i])
            break
        ch = enc[i]
        if ch in "{([":
            close = {"{": "}", "(": ")", "[": "]"}[ch]
            depth = 0
            while i < n:
                if enc[i] in "{([":
                    depth += 1
                elif enc[i] in "})]":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        else:
            i += 1
        out.append(enc[start:i])
    return out


def human(tok: str) -> str:
    """把一个 encoding token 变成可读类型名。"""
    if not tok:
        return "?"
    ptr = ""
    j = 0
    while j < len(tok) and tok[j] in "rnNoORV":
        j += 1
    body = tok[j:]
    while body.startswith("^"):
        ptr += "*"
        body = body[1:]
    if body.startswith("@\""):
        return body[2:-1].rstrip('"') + "*" + ptr
    if body.startswith("{"):
        name = body[1:].split("=", 1)[0]
        return ("struct " + (name if name != "?" else "anon")) + ptr
    if body.startswith("("):
        name = body[1:].split("=", 1)[0]
        return ("union " + (name if name != "?" else "anon")) + ptr
    if body.startswith("["):
        return "array" + ptr
    return PRIM.get(body, body) + ptr


def decode(enc: str) -> tuple[str, list[str]]:
    toks = split_encoding(enc)
    if not toks:
        return ("?", [])
    ret = human(toks[0])
    args = [human(t) for t in toks[3:]] if len(toks) > 3 else []
    return (ret, args)


# ---------------------------------------------------------------------------
# 按名字模式分组。只用于排序与阅读，不参与处置判定。
# ---------------------------------------------------------------------------

GROUPS: list[tuple[str, str]] = [
    (r"^new[A-Z]", "工厂（new*，返回 +1）"),
    (r"^(supports|is[A-Z]|are[A-Z]|has[A-Z]|can[A-Z]|should[A-Z])", "能力查询"),
    (r"^(max|min)[A-Z]", "limits"),
    (r"^(init|_init)", "init 链"),
    (r"(Size|Length|Count|Alignment|Width|Height|Bytes)$", "尺寸与对齐查询"),
    (r"^set[A-Z]", "setter"),
    (r"(Label|label|Name|name|Description|description)", "标识与调试"),
    (r"^(begin|end|flush|commit|submit|wait|signal|notify)", "生命周期与同步"),
    (r"(Counter|counter|Sample|sample|Statistic)", "计数与采样"),
    (r"(Heap|heap|Buffer|buffer|Texture|texture|Resource|resource)", "资源"),
    (r"(Pipeline|pipeline|Library|library|Function|function|Variant|variant)", "着色器与管线"),
    (r"(Argument|argument|Binding|binding)", "绑定与 argument buffer"),
    (r"^_", "私有（下划线前缀）"),
]


def group_of(sel: str) -> str:
    for pat, name in GROUPS:
        if re.search(pat, sel):
            return name
    return "其它"


# ---------------------------------------------------------------------------
# 处置判定
# ---------------------------------------------------------------------------

def disposition(in_base: bool, in_family: bool, in_apv: bool,
                required: bool) -> tuple[str, str]:
    """返回 (处置, 理由)。四格判定，见模块文档。"""
    if in_base and in_apv:
        return ("必须覆写", "基类有答案但 APV 覆写了它 —— 说明基类答案对半虚拟化设备不成立")
    if in_base and not in_apv:
        if in_family:
            return ("继承家族", "`MTLIOAccelDevice` 已答，APV 不覆写")
        return ("继承基类", "`_MTLDevice` 已答，APV 不覆写")
    if not in_base and in_apv:
        return ("必须实现", "没有可继承的答案，APV 自己实现了")
    # 四格里唯一需要人工的一格
    if required:
        return ("待定(required)", "协议 required 但三个类都没 IMP —— 查 `42` 分册的落点")
    return ("可不实现(optional)", "协议 optional 且三个类都没 IMP")


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "ci-evidence/objc-dump/objc-dump.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "docs/spec/23-DEVICE-SPI-DISPOSITION.md"

    with open(src, encoding="utf-8") as f:
        d = json.load(f)

    cls = d["classes"]
    pro = d["protocols"]

    def imp_set(name: str) -> dict[str, str]:
        c = cls.get(name, {})
        if not c.get("present"):
            return {}
        return {m["sel"]: m["enc"] for m in c["instanceMethods"]}

    base = imp_set("_MTLDevice")
    family = imp_set("MTLIOAccelDevice")
    apv = imp_set("AppleParavirtDevice")

    # 协议声明：MTLDeviceSPI 继承 MTLDevice，两者都要
    rows: dict[str, dict] = {}
    for pname in ("MTLDevice", "MTLDeviceSPI"):
        p = pro.get(pname, {})
        if not p.get("present"):
            print(f"warn: 协议 {pname} 不在转储里", file=sys.stderr)
            continue
        for bucket, req in (("requiredInstance", True), ("optionalInstance", False)):
            for m in p[bucket]["methods"]:
                sel = m["sel"]
                # MTLDeviceSPI 对 MTLDevice 有重复声明，先到先得并记下重复
                if sel in rows:
                    rows[sel]["protocols"].add(pname)
                    continue
                rows[sel] = {
                    "sel": sel,
                    "enc": m["enc"],
                    "required": req,
                    "protocols": {pname},
                }

    # 填处置
    for r in rows.values():
        sel = r["sel"]
        r["in_base"] = sel in base
        r["in_family"] = sel in family
        r["in_apv"] = sel in apv
        r["disp"], r["why"] = disposition(
            r["in_base"], r["in_family"], r["in_apv"], r["required"])
        r["group"] = group_of(sel)
        r["ret"], r["args"] = decode(r["enc"])

    # ---- 统计 ----
    disp_count = Counter(r["disp"] for r in rows.values())
    group_count = Counter(r["group"] for r in rows.values())
    spi_only = [r for r in rows.values() if r["protocols"] == {"MTLDeviceSPI"}]
    both = [r for r in rows.values() if len(r["protocols"]) == 2]

    # ---- 写文档 ----
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    w = open(dst, "w", encoding="utf-8", newline="\n").write

    w("# 23 `MTLDevice` / `MTLDeviceSPI` 的逐方法处置表\n\n")
    w("文档版本：1.0（**本文由 `tools/ci/gen_device_spi_table.py` 生成，不要手改**）\n")
    w(f"数据来源：`{src}`（schema `{d.get('schema')}`）\n")
    w("采集平台：macOS 26.6.1 / 25G76 的 `macos-26-intel` 运行器，见 `91-RUNTIME-EVIDENCE.md`\n")
    w("证据等级：**`TESTED(25G76)`**（运行期 `class_copyMethodList` 与 "
      "`protocol_copyMethodDescriptionList` 直接读出，不是静态推断）\n")
    w("上级文档：`00-OVERVIEW.md`　配套：`20-OBJC-DEVICE.md`、"
      "`21-OBJC-OBJECT-FAMILY.md`、`42-RUNTIME-MAPPING.md`\n\n")

    w("## 0. 本文补的是什么\n\n")
    w("`21-OBJC-OBJECT-FAMILY.md` 第 8.2 节明说「`MTLDeviceSPI` 的 507 条不逐条抄进本文」，"
      "所以在本文之前，那 507 条只有分类普查与 28 条交集，**没有逐条处置**。实现者照着它"
      "无法回答「这一条我要不要写」。\n\n")
    w("本文给出逐条答案，而且答案是**从运行期转储机械推出的**，不是人工判断。\n\n")

    w("### 0.1 判定规则\n\n")
    w("转储给了三个类的完整 IMP 集合（`TESTED(25G76)`）：\n\n")
    w("| 类 | IMP 数 | 角色 |\n|---|---:|---|\n")
    w(f"| `_MTLDevice` | {len(base)} | 基类 |\n")
    w(f"| `MTLIOAccelDevice` | {len(family)} | 家族节点（本项目的 Device 继承它） |\n")
    w(f"| `AppleParavirtDevice` | {len(apv)} | 参考实现 |\n\n")
    w("「必须覆写 vs 可以继承」（`21` 第 10 节）就是这三个集合的布尔组合：\n\n")
    w("| 基类有 | APV 覆写 | 处置 | 理由 |\n|---|---|---|---|\n")
    w("| ✅ | ✅ | **必须覆写** | 基类有答案但 APV 覆写了 —— 说明基类答案对半虚拟化设备不成立 |\n")
    w("| ✅ | ❌ | **继承** | 参考实现都不覆写，我们也不用 |\n")
    w("| ❌ | ✅ | **必须实现** | 没有可继承的答案 |\n")
    w("| ❌ | ❌ | required 则**待定**，optional 则**可不实现** | 四格里唯一需要人工的一格 |\n\n")
    w("**第三格（必须实现）与第一格（必须覆写）合起来就是第一版的工作量下界。**\n\n")

    w("### 0.2 一条重要的读法限制\n\n")
    w("「继承」不等于「不用管」。它的准确含义是**第一版不用写这一条**，因为 "
      "`MTLIOAccelDevice` 或 `_MTLDevice` 的实现会被调到。但那些实现可能依赖本项目"
      "没有提供的东西（`20` 第 8 节逐条分析了 resource 层的 `init*` 全部真打内核）。"
      "所以「继承」的行必须在 `20`/`21` 的继承分析里交叉验证过才能真的放手。\n\n")

    w("## 1. 总计\n\n")
    w(f"协议声明合计 **{len(rows)}** 条不同 selector")
    w(f"（`MTLDevice` 与 `MTLDeviceSPI` 重复声明 {len(both)} 条，"
      f"只属 `MTLDeviceSPI` 的 {len(spi_only)} 条）。\n\n")
    w("| 处置 | 条数 | 占比 |\n|---|---:|---:|\n")
    for k, v in sorted(disp_count.items(), key=lambda x: -x[1]):
        w(f"| {k} | {v} | {v * 100 / len(rows):.1f}% |\n")
    must = disp_count.get("必须覆写", 0) + disp_count.get("必须实现", 0)
    w(f"\n**第一版必须自己写的是 {must} 条**"
      f"（必须覆写 {disp_count.get('必须覆写', 0)} + 必须实现 {disp_count.get('必须实现', 0)}）。\n\n")

    w("### 1.1 按语义分组\n\n| 分组 | 条数 |\n|---|---:|\n")
    for k, v in sorted(group_count.items(), key=lambda x: -x[1]):
        w(f"| {k} | {v} |\n")
    w("\n")

    w("## 2. 必须自己写的（逐条）\n\n")
    for want in ("必须覆写", "必须实现"):
        sub = sorted([r for r in rows.values() if r["disp"] == want],
                     key=lambda r: (r["group"], r["sel"]))
        w(f"### 2.{1 if want == '必须覆写' else 2} {want}（{len(sub)} 条）\n\n")
        w("| selector | 返回 | 参数 | 分组 | 协议 |\n|---|---|---|---|---|\n")
        for r in sub:
            protos = "+".join(sorted(r["protocols"]))
            args = ", ".join(r["args"]) if r["args"] else "—"
            flag = "" if r["required"] else " *(opt)*"
            w(f"| `{r['sel']}`{flag} | `{r['ret']}` | {args} | {r['group']} | {protos} |\n")
        w("\n")

    w("## 3. 待定：协议 required 但三个类都没 IMP\n\n")
    pend = sorted([r for r in rows.values() if r["disp"].startswith("待定")],
                  key=lambda r: (r["group"], r["sel"]))
    w(f"**{len(pend)} 条。这一格是本表唯一需要人工的部分。**\n\n")
    w("`required` 却连参考实现都不答，有三种可能，必须逐条区分：\n\n")
    w("1. Metal.framework 的基类在**更上层**答了（`NSObject` 或 category），转储没覆盖到；\n")
    w("2. 它在实践中永不被调用（协议声明是历史包袱）；\n")
    w("3. **它确实需要我们答，而 APV 走的是另一条路绕开了它。**\n\n")
    w("第 3 类是风险所在。处置：查 `42-RUNTIME-MAPPING.md` 第 5.20 节的落点，"
      "有落点的照表转发；没有的进 `42` 第 7 节的新 gap 清单。\n\n")
    w("| selector | 返回 | 参数 | 分组 |\n|---|---|---|---|\n")
    for r in pend:
        args = ", ".join(r["args"]) if r["args"] else "—"
        w(f"| `{r['sel']}` | `{r['ret']}` | {args} | {r['group']} |\n")
    w("\n")

    w("## 4. 可以继承的（分组计数 + 全表）\n\n")
    inh = sorted([r for r in rows.values() if r["disp"].startswith("继承")],
                 key=lambda r: (r["disp"], r["group"], r["sel"]))
    c2 = Counter((r["disp"], r["group"]) for r in inh)
    w("| 处置 | 分组 | 条数 |\n|---|---|---:|\n")
    for (dd, gg), v in sorted(c2.items(), key=lambda x: -x[1]):
        w(f"| {dd} | {gg} | {v} |\n")
    w(f"\n<details>\n<summary>全部 {len(inh)} 条</summary>\n\n")
    w("| selector | 返回 | 处置 |\n|---|---|---|\n")
    for r in inh:
        w(f"| `{r['sel']}` | `{r['ret']}` | {r['disp']} |\n")
    w("\n</details>\n\n")

    w("## 5. 可不实现的 optional\n\n")
    opt = sorted([r for r in rows.values() if r["disp"].startswith("可不实现")],
                 key=lambda r: r["sel"])
    w(f"{len(opt)} 条。协议 optional 且三个类都没 IMP，"
      "即 Metal 不会假定它存在、参考实现也没提供。**第一版全部不实现。**\n\n")
    w(f"<details>\n<summary>全部 {len(opt)} 条</summary>\n\n")
    w("| selector | 返回 |\n|---|---|\n")
    for r in opt:
        w(f"| `{r['sel']}` | `{r['ret']}` |\n")
    w("\n</details>\n\n")

    w("## 6. 重新生成\n\n")
    w("```powershell\n")
    w("# 1) 取运行期转储\n")
    w("gh workflow run evidence-macos26-intel.yml --ref main\n")
    w("$id = gh run list --workflow=evidence-macos26-intel.yml --limit 1 "
      "--json databaseId --jq '.[0].databaseId'\n")
    w("gh run download $id --dir ci-evidence\n\n")
    w("# 2) 重新生成本文\n")
    w(f"py tools\\ci\\gen_device_spi_table.py {src} {dst}\n")
    w("```\n\n")
    w("**本文不要手改。** 要改判定规则就改 "
      "`tools/ci/gen_device_spi_table.py` 的 `disposition()`，"
      "这样规则本身是可 review、可 diff 的。\n")

    print(f"wrote {dst}")
    print(f"  {len(rows)} 条不同 selector")
    for k, v in sorted(disp_count.items(), key=lambda x: -x[1]):
        print(f"  {k:24} {v:4}")
    print(f"  -> 第一版必须自己写 {must} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
