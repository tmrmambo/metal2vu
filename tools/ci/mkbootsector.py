#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一个 512 字节的 x86 引导扇区：往串口逐字节写一行字，然后停机。

为什么需要它
------------
`hv_vm_create` 返回 HV_SUCCESS 只说明 Hypervisor.framework 发给我们一个 VM
句柄。它**不证明 guest 的指令被执行过** —— 嵌套虚拟化不可用时的常见形态恰恰是
「句柄拿得到、内存也映射得上，vCPU 一 run 就立刻退出」。所以探针分两级：

    一级  tools/hvf/hvf_probe.c  直接问 framework：VM / 内存映射 / vCPU 三步
    二级  本文件 + QEMU -accel hvf  让 guest 真跑一段代码，并把结果带出来

带出来的办法取最笨也最可靠的那个：往 0x3F8（COM1 的发送保持寄存器）逐字节写，
QEMU 的 `-serial file:…` 把字节落到宿主的一个文件里。于是「guest 执行过代码」
这件事在宿主侧变成一个可以 grep 的字符串，而不是一句推断。

消息由调用方给（workflow 里传 run id），所以读到的串不可能是上一轮留下的。

关于串口不做初始化
------------------
正常的串口驱动要先设 LCR/DLAB 再设波特率。这里不设：16550A 复位后 DLAB=0，
写 0x3F8 就是写 THR，QEMU 的模型会把这个字节直接转发给 chardev。少几条指令，
少几个可能编错的位移。

子命令
------
    mkbootsector.py create out.img --message HVFGUEST-123 [--size 1MiB]
    mkbootsector.py dump out.img
    mkbootsector.py selftest
"""
from __future__ import annotations

import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

SECTOR = 512
LOAD_ADDR = 0x7C00  # BIOS 把引导扇区读到 0000:7C00 并跳进去
SERIAL_THR = 0x03F8  # COM1 的 THR
BOOT_SIG = 0xAA55

# `mov si, imm16` 的立即数在代码里的偏移：xor(2) + mov ds(2) + mov dx(3) + 操作码(1)
MSG_ADDR_OFF = 8


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------
def _emit(msg_addr: int) -> bytes:
    """实模式 16 位代码。msg_addr 是消息在段 0 内的绝对偏移。

        xor ax, ax          ; 不假定 BIOS 把 DS 置了 0
        mov ds, ax
        mov dx, 0x03F8
        mov si, msg
    loop:
        mov al, [si]
        cmp al, 0
        jz  done
        out dx, al
        inc si
        jmp loop
    done:
        hlt
        jmp done
    """
    b = bytearray()
    b += b"\x31\xc0"  # xor ax, ax
    b += b"\x8e\xd8"  # mov ds, ax
    b += b"\xba" + struct.pack("<H", SERIAL_THR)  # mov dx, imm16
    b += b"\xbe" + struct.pack("<H", msg_addr)  # mov si, imm16
    loop = len(b)
    b += b"\x8a\x04"  # mov al, [si]
    b += b"\x3c\x00"  # cmp al, 0
    jz_at = len(b)
    b += b"\x74\x00"  # jz done   —— 位移稍后回填
    b += b"\xee"  # out dx, al
    b += b"\x46"  # inc si
    b += b"\xeb" + bytes([(loop - (len(b) + 2)) & 0xFF])  # jmp loop
    done = len(b)
    b += b"\xf4"  # hlt
    b += b"\xeb\xfd"  # jmp -3 → 回到 hlt
    b[jz_at + 1] = (done - (jz_at + 2)) & 0xFF
    return bytes(b)


def build_sector(message: bytes) -> bytes:
    """返回 512 字节的引导扇区。"""
    if b"\x00" in message:
        raise ValueError("消息里不能有 NUL —— 它是终止符")
    payload = message + b"\r\n\x00"
    # 代码长度与 msg_addr 无关（imm16 定宽），所以先编一次拿长度，再回填地址。
    code_len = len(_emit(0))
    code = _emit(LOAD_ADDR + code_len)
    if len(code) != code_len:
        raise AssertionError("两趟编码长度不一致，编码器有问题")
    body = code + payload
    room = SECTOR - 2
    if len(body) > room:
        raise ValueError(f"消息太长：代码+消息 {len(body)} 字节 > {room}")
    return body + b"\x00" * (room - len(body)) + struct.pack("<H", BOOT_SIG)


def build_image(message: bytes, size: int) -> bytes:
    if size < SECTOR or size % SECTOR:
        raise ValueError(f"镜像大小必须是 {SECTOR} 的整数倍且不小于一个扇区")
    sec = build_sector(message)
    return sec + b"\x00" * (size - len(sec))


def parse_message(sector: bytes) -> bytes:
    """从扇区里把消息读回来（selftest 的往返检查用）。"""
    if len(sector) < SECTOR:
        raise ValueError("短于一个扇区")
    if struct.unpack_from("<H", sector, SECTOR - 2)[0] != BOOT_SIG:
        raise ValueError("缺少 0x55AA 引导签名")
    msg_addr = struct.unpack_from("<H", sector, MSG_ADDR_OFF)[0]  # `mov si, imm16` 的 imm
    off = msg_addr - LOAD_ADDR
    end = sector.index(b"\x00", off)
    payload = bytes(sector[off:end])
    # build_sector 在消息后面补了 CRLF 才是 NUL，这里把它去掉，返回调用方给过的那串
    return payload[:-2] if payload.endswith(b"\r\n") else payload


# ---------------------------------------------------------------------------
# 一个只认这九条指令的 16 位解释器
# ---------------------------------------------------------------------------
# 为什么要写它：这份扇区里真正会错的东西是两个相对位移（jz 和 jmp）。位移错了
# 扇区照样是 512 字节、照样有 0x55AA、照样能被 BIOS 加载 —— 症状会是「QEMU 下
# 串口文件空」，而那和「HVF 不可用」长得一模一样。于是本该归因到 hypervisor 的
# 一次判定会被自己的 bug 污染。所以自检不检查字节，检查行为。
def simulate(sector: bytes, max_steps: int = 100000) -> bytes:
    mem = bytearray(0x100000)
    mem[LOAD_ADDR : LOAD_ADDR + SECTOR] = sector[:SECTOR]
    ip = LOAD_ADDR
    ax = 0xDEAD  # 故意给非零初值：代码必须自己把 DS 置零
    dx = 0xBEEF
    si = 0xFFFF
    ds = 0xF000  # 同上，故意不是 0
    out: bytearray = bytearray()

    def al() -> int:
        return ax & 0xFF

    for _ in range(max_steps):
        op = mem[ip]
        if op == 0x31 and mem[ip + 1] == 0xC0:  # xor ax, ax
            ax = 0
            ip += 2
        elif op == 0x8E and mem[ip + 1] == 0xD8:  # mov ds, ax
            ds = ax
            ip += 2
        elif op == 0xBA:  # mov dx, imm16
            dx = struct.unpack_from("<H", mem, ip + 1)[0]
            ip += 3
        elif op == 0xBE:  # mov si, imm16
            si = struct.unpack_from("<H", mem, ip + 1)[0]
            ip += 3
        elif op == 0x8A and mem[ip + 1] == 0x04:  # mov al, [si]
            ax = (ax & 0xFF00) | mem[(ds << 4) + si]
            ip += 2
        elif op == 0x3C:  # cmp al, imm8
            zf = al() == mem[ip + 1]
            ip += 2
        elif op == 0x74:  # jz rel8
            disp = struct.unpack_from("<b", mem, ip + 1)[0]
            ip += 2
            if zf:
                ip += disp
        elif op == 0xEE:  # out dx, al
            if dx != SERIAL_THR:
                raise AssertionError(f"往错误的端口写：0x{dx:04x}")
            out.append(al())
            ip += 1
        elif op == 0x46:  # inc si
            si = (si + 1) & 0xFFFF
            ip += 1
        elif op == 0xEB:  # jmp rel8
            disp = struct.unpack_from("<b", mem, ip + 1)[0]
            ip += 2 + disp
        elif op == 0xF4:  # hlt
            return bytes(out)
        else:
            raise AssertionError(f"解释器不认识的操作码 0x{op:02x} @ 0x{ip:04x}")
    raise AssertionError("步数用尽 —— 代码里有死循环，位移大概编错了")


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def parse_size(s: str) -> int:
    s = s.strip()
    units = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}
    for suffix, mul in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if s.upper().endswith(suffix):
            return int(float(s[: -len(suffix)]) * mul)
    return int(s)


def cmd_create(argv: list[str]) -> int:
    if not argv:
        print("用法: mkbootsector.py create out.img --message M [--size 1MiB]")
        return 2
    out = argv[0]
    message = None
    size = 1024 * 1024
    i = 1
    while i < len(argv):
        if argv[i] == "--message":
            message = argv[i + 1]
            i += 2
        elif argv[i] == "--size":
            size = parse_size(argv[i + 1])
            i += 2
        else:
            print(f"不认识的参数: {argv[i]}")
            return 2
    if not message:
        print("必须给 --message")
        return 2
    img = build_image(message.encode("ascii"), size)
    with open(out, "wb") as f:
        f.write(img)
    sec = img[:SECTOR]
    print(f"写出 {out}  {len(img)} 字节（引导扇区 {SECTOR} + 填充）")
    print(f"  消息      : {message!r}")
    print(f"  代码长度  : {len(_emit(0))} 字节，消息起于 0x{LOAD_ADDR + len(_emit(0)):04X}")
    print(f"  引导签名  : 0x{struct.unpack_from('<H', sec, SECTOR - 2)[0]:04X}")
    print(f"  解释器跑一遍，guest 会往 0x3F8 吐: {simulate(sec)!r}")
    return 0


def cmd_dump(argv: list[str]) -> int:
    if not argv:
        print("用法: mkbootsector.py dump out.img")
        return 2
    sec = open(argv[0], "rb").read(SECTOR)
    code_len = len(_emit(0))
    print(f"-- 代码 {code_len} 字节 --")
    print("  " + " ".join(f"{b:02x}" for b in sec[:code_len]))
    print(f"-- 消息 --\n  {parse_message(sec)!r}")
    print(f"-- 签名 @ {SECTOR - 2} --\n  0x{struct.unpack_from('<H', sec, SECTOR - 2)[0]:04X}")
    print(f"-- 解释器输出 --\n  {simulate(sec)!r}")
    return 0


def cmd_selftest(_argv: list[str]) -> int:
    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'ok' if cond else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")
        if not cond:
            fails.append(name)

    print("== 布局 ==")
    sec = build_sector(b"HVFGUEST-1")
    check("扇区正好 512 字节", len(sec) == SECTOR, f"{len(sec)}")
    check(
        "0x55AA 在 510",
        struct.unpack_from("<H", sec, SECTOR - 2)[0] == BOOT_SIG,
    )
    code_len = len(_emit(0))
    check("代码 23 字节", code_len == 23, f"{code_len}")
    check(
        "msg_addr 紧跟代码",
        struct.unpack_from("<H", sec, MSG_ADDR_OFF)[0] == LOAD_ADDR + code_len,
        f"0x{struct.unpack_from('<H', sec, MSG_ADDR_OFF)[0]:04X}",
    )

    print("== 黄金向量（消息 'X'）==")
    want = bytes.fromhex(
        "31c0" "8ed8" "baf803" "be177c" "8a04" "3c00" "7404" "ee" "46" "ebf6" "f4" "ebfd"
    ) + b"X\r\n\x00"
    got = build_sector(b"X")[: len(want)]
    check("字节逐一相同", got == want, "" if got == want else f"\n     期望 {want.hex()}\n     实得 {got.hex()}")

    print("== 行为（16 位解释器）==")
    for msg in (b"X", b"HVFGUEST-41290358784", b"a" * 400):
        out = simulate(build_sector(msg))
        check(f"消息 {len(msg)} 字节原样吐到 0x3F8", out == msg + b"\r\n", f"{out[:24]!r}")
    check("往返解析", parse_message(build_sector(b"RT-9")) == b"RT-9")

    # 把 23 个代码字节逐个 +1，看行为变不变。这比手挑几个字节诚实：它会把
    # 「哪些字节是承重的」整张图画出来，编码器一改就会对不上。
    #
    # 恰好三个字节在正常路径上是死的，而且这三个都属于同一件事 ——
    # 收尾处 `hlt` / `jmp done` 那两条里的 `jmp`：一旦消息写完就 jz 到 hlt 停住，
    # 后面那条 jmp 只在「hlt 被中断唤醒」时才会执行，而本扇区从不开中断。
    # 它是防御性的，不是功能性的，所以篡改它无可观测后果 —— 这是预期，不是漏洞。
    print("== 承重字节图（逐字节 +1，看行为变不变）==")
    base_sec = build_sector(b"X")
    base_out = simulate(base_sec)
    neutral: list[int] = []
    for off in range(code_len):
        bad = bytearray(base_sec)
        bad[off] = (bad[off] + 1) & 0xFF
        try:
            changed = simulate(bytes(bad)) != base_out
        except AssertionError:
            changed = True  # 解释器直接拒掉，当然算行为变了
        if not changed:
            neutral.append(off)
    expect_neutral = [15, 21, 22]  # jz 的位移 / `jmp done` 的操作码与位移
    check(
        f"承重字节 {code_len - len(neutral)}/{code_len}，中性字节恰为收尾那三个",
        neutral == expect_neutral,
        f"中性={neutral} 期望={expect_neutral}",
    )
    for off in (MSG_ADDR_OFF, MSG_ADDR_OFF + 1, 5, 13, 19):
        check(f"偏移 {off} 是承重的", off not in neutral)

    print("== 边界 ==")
    for bad_input, label in (
        (b"a" * 500, "消息过长"),
        (b"a\x00b", "消息含 NUL"),
    ):
        try:
            build_sector(bad_input)
            check(label + " 被拒", False, "竟然接受了")
        except ValueError:
            check(label + " 被拒", True)
    try:
        build_image(b"X", 777)
        check("镜像大小非扇区倍数被拒", False, "竟然接受了")
    except ValueError:
        check("镜像大小非扇区倍数被拒", True)

    print()
    if fails:
        print(f"自检失败 {len(fails)} 项: {', '.join(fails)}")
        return 1
    print("自检全过")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    table = {"create": cmd_create, "dump": cmd_dump, "selftest": cmd_selftest}
    fn = table.get(argv[1])
    if fn is None:
        print(f"不认识的子命令 {argv[1]!r}；有 {', '.join(table)}")
        return 2
    return fn(argv[2:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
