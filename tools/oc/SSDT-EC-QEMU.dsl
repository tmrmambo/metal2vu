/*
 * SSDT-EC-QEMU.dsl
 * 给 QEMU/OVMF 的 macOS guest 提供一个假的 embedded controller。
 * macOS 10.15 起要求容器内存在一个 EC 设备。
 * 规格: docs/spec/76-BOOT-LAYOUT-PICKER.md 第 5.3.1 节
 *
 * 与 dortania 的桌面版差异：父设备用 \_SB.PCI0 而不是 \_SB.PCI0.LPCB，
 * 因为 QEMU 的 DSDT 里没有名为 LPCB 的 LPC 桥（76 §5.3.1，INFERRED）。
 *
 * 这条 INFERRED 登记为 L-015，而且它的失败形态很坏：
 * 「不报错但 EC 不存在」。71 §6.2 自己留的警告就是这一条 ——
 * 选错版本的表现是 AppleACPIEC 匹配不上，而不是报错。
 * 76 §5.3.1 给了三条验证方法，最便宜的那条不需要 macOS：
 * 在任意 Linux guest 里 acpidump -b 然后 iasl -d dsdt.dat，
 * grep 'Device ((ISA|LPC|LPCB|SBRG))' 看 QEMU 的 LPC 桥到底叫什么。
 *
 * 编译（Linux 构建机，一条命令）:
 *   iasl -ve SSDT-EC-QEMU.dsl        # 产出 SSDT-EC-QEMU.aml
 *   mv SSDT-EC-QEMU.aml <stage>/EFI/OC/ACPI/SSDT-EC.aml
 */
DefinitionBlock ("", "SSDT", 2, "M2VU", "ECQEMU", 0x00000000)
{
    External (_SB_.PCI0, DeviceObj)

    Scope (\_SB.PCI0)
    {
        Device (EC)
        {
            /* ACID0001 是社区约定的假 EC 的 _HID，不与任何真实硬件冲突 */
            Name (_HID, "ACID0001")

            /* 只在 macOS 下存在。_OSI("Darwin") 为假时返回 0，
             * 这样同一块盘拿去装别的系统时这个设备不出现。 */
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}
