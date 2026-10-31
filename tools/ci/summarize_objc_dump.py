#!/usr/bin/env python3
"""把 CI 产出的 objc-dump.json 摘成可读报告，并与规格分册里的断言逐条核对。

用法：py tools/ci/summarize_objc_dump.py ci-evidence/objc-dump/objc-dump.json
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "ci-evidence/objc-dump/objc-dump.json"
with open(path, encoding="utf-8") as f:
    d = json.load(f)

print("=" * 72)
print("枚举到的 Metal device")
print("=" * 72)
for x in d["devices"]:
    for k, v in x.items():
        print(f"  {k:12} = {v}")
    print()

print("=" * 72)
print("加载的 Metal 相关镜像")
print("=" * 72)
for x in d["metal_images"]:
    print("  " + x)

print()
print("=" * 72)
print("协议条目数（核对 20/21 分册的 required/optional 断言）")
print("=" * 72)
print(f"  {'协议':30} {'required':>9} {'optional':>9}   继承")
for k, v in sorted(d["protocols"].items()):
    if not v.get("present"):
        print(f"  {k:30} {'ABSENT':>9}")
        continue
    inh = ",".join(v["inherits"]) or "-"
    print(f"  {k:30} {v['totalRequired']:>9} {v['totalOptional']:>9}   {inh}")

print()
print("=" * 72)
print("类：是否存在、继承链、instance size、方法数")
print("=" * 72)
for k, v in sorted(d["classes"].items()):
    if not v.get("present"):
        print(f"  {k:42} ABSENT")
        continue
    chain = " -> ".join(v["superchain"][:4]) or "-"
    print(f"  {k:42} size={v['instanceSize']:<6} "
          f"im={len(v['instanceMethods']):<4} cm={len(v['classMethods']):<3} "
          f"ivar={len(v['ivars']):<3} {chain}")

# ---- 定向核对 ----
print()
print("=" * 72)
print("定向核对")
print("=" * 72)


def chk(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


cls = d["classes"]
pro = d["protocols"]

# 20 分册：MTLIOAccelDevice 无前导下划线，_MTLDevice 是其父类
a = cls.get("MTLIOAccelDevice", {})
chk("MTLIOAccelDevice 存在（无前导下划线）", a.get("present") is True)
chk("_MTLDevice 是 MTLIOAccelDevice 的父类",
    a.get("present") and a["superchain"][:1] == ["_MTLDevice"],
    f"实际 superchain={a.get('superchain')}")

# 21 分册：MTLDeviceSPI = 427 required + 80 optional
sp = pro.get("MTLDeviceSPI", {})
if sp.get("present"):
    chk("MTLDeviceSPI required == 427", sp["totalRequired"] == 427,
        f"实际 {sp['totalRequired']}")
    chk("MTLDeviceSPI optional == 80", sp["totalOptional"] == 80,
        f"实际 {sp['totalOptional']}")
    chk("MTLDeviceSPI 合计 == 507",
        sp["totalRequired"] + sp["totalOptional"] == 507,
        f"实际 {sp['totalRequired'] + sp['totalOptional']}")
else:
    chk("MTLDeviceSPI 存在", False)

# 21 分册：七个 MTLIOAccel* 节点
seven = ["MTLIOAccelDevice", "MTLIOAccelCommandQueue", "MTLIOAccelCommandBuffer",
         "MTLIOAccelBuffer", "MTLIOAccelTexture", "MTLIOAccelPooledResource",
         "MTLIOAccelHeap"]
have = [n for n in seven if cls.get(n, {}).get("present")]
chk("七个 MTLIOAccel* 节点全部存在", len(have) == 7,
    f"存在 {len(have)}/7：缺 {sorted(set(seven) - set(have))}")

# 21 分册：encoder 与 state 无 MTLIOAccel* 版本，走 _MTL* 抽象层
for n in ["_MTLRenderCommandEncoder", "_MTLComputeCommandEncoder",
          "_MTLRenderPipelineState", "_MTLComputePipelineState"]:
    chk(f"{n} 存在（encoder/state 走 _MTL* 层）",
        cls.get(n, {}).get("present") is True)

# 20 分册：library 与 function 无 MTLIOAccel* 类
chk("_MTLLibrary 存在", cls.get("_MTLLibrary", {}).get("present") is True)
chk("_MTLFunction 存在", cls.get("_MTLFunction", {}).get("present") is True)

# 32 分册：MTLCompiler 类存在，且带 initWithTargetData:... 形态的 init
mc = cls.get("MTLCompiler", {})
chk("MTLCompiler 类存在", mc.get("present") is True)
if mc.get("present"):
    inits = [m["sel"] for m in mc["instanceMethods"]
             if m["sel"].startswith("initWith")]
    chk("MTLCompiler 有 initWithTargetData: 系列", bool(inits), f"{inits}")

# 60 分册：Metal 4 必须为 false
for dev in d["devices"]:
    if "famMetal4" in dev:
        chk(f"device '{dev.get('name')}' supportsFamily(Metal4) == false",
            dev["famMetal4"] in (0, False),
            f"实际 {dev['famMetal4']}")

# 20 分册：argumentBuffersSupport 必须是 0 或 1
for dev in d["devices"]:
    if "argBufTier" in dev:
        chk(f"device '{dev.get('name')}' argumentBuffersSupport ∈ {{0,1}}",
            dev["argBufTier"] in (0, 1), f"实际 {dev['argBufTier']}")

# 5 个协议外虚方法：20 分册说它们不在任何协议里，是 _MTLDevice 的虚方法
FIVE = ["newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:",
        "newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:",
        "newComputeVariantWithCompilerOutput:pipelineStatisticsOutput:",
        "newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:",
        "newComputePipelineWithDescriptor:variant:errorMessage:"]
md = cls.get("_MTLDevice", {})
if md.get("present"):
    sels = {m["sel"] for m in md["instanceMethods"]}
    for s in FIVE:
        chk(f"_MTLDevice 有 {s[:52]}", s in sels)
    # 并确认它们确实不在协议里
    all_proto_sels = set()
    for v in pro.values():
        if not v.get("present"):
            continue
        for bucket in ("requiredInstance", "optionalInstance",
                       "requiredClass", "optionalClass"):
            all_proto_sels |= {m["sel"] for m in v[bucket]["methods"]}
    leaked = [s for s in FIVE if s in all_proto_sels]
    chk("那 5 个方法确实不在任何被查协议里", not leaked, f"泄漏 {leaked}")

print()
print("提示：PASS/FAIL 中的 FAIL 不一定是规格写错，也可能是运行器的 macOS")
print(f"      版本（{d.get('schema')} 采集自 26.6.1 / 25G76）与目标 25G325 存在差异。")
