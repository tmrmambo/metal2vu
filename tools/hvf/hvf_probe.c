/*
 * hvf_probe.c —— 问一个问题：GitHub 的 macos-26-intel 运行器里，
 * Hypervisor.framework 到底能不能真的建出一个 VM。
 *
 * 为什么这一条决定整条路
 * ----------------------
 * 运行器自己就是一台 KVM guest（docs/spec/91-RUNTIME-EVIDENCE.md 第 1 节：
 * GPU 是 `Apple Paravirtual device`）。所以在它里面再跑一个 VM 是**嵌套虚拟化**。
 * `bake` 的 probe 实测 `kern.hv_support = 1` 且 `kern.hv_vmm_present = 1`，
 * 但前者只表示 macOS 内核认为 VMX 可用，**不保证 KVM 宿主真的把嵌套打开了**。
 *
 * 如果这一条不成立，「在 CI 里把造出来的盘启动起来」整条路就不存在，
 * V-025（自建盘能不能引导）必须回到真机，图形栈的测试条件也跟着推迟。
 * 所以它比造盘更该先做，而且只要几秒。
 *
 * Hypervisor.framework 需要 entitlement `com.apple.security.hypervisor`。
 * 注意它是**公开**的 entitlement（不是 `com.apple.private.*`），所以
 * ad-hoc 签名就能带上 —— 这一点和 78 §A.10.2d-bis 里 `fs_snapshot_create`
 * 要的那个 restricted entitlement 不同，后者 AMFI 开着时自签名会被拒。
 *
 * 编译与签名
 * ----------
 *     cc -O2 -Wall -Wextra -framework Hypervisor -o hvf_probe hvf_probe.c
 *     codesign -s - --entitlements hvf.entitlements -f hvf_probe
 *
 * 退出码
 * ------
 *     0  hv_vm_create 成功（嵌套虚拟化可用）
 *     1  hv_vm_create 失败，错误码已打印
 *     2  参数/环境问题
 */

#include <Hypervisor/hv.h>
#include <Hypervisor/hv_vmx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>

static void read_sysctl_int(const char *name)
{
    int v = -1;
    size_t len = sizeof(v);
    if (sysctlbyname(name, &v, &len, NULL, 0) == 0)
        printf("  %-28s = %d\n", name, v);
    else
        printf("  %-28s = (unavailable)\n", name);
}

static const char *hv_err(hv_return_t r)
{
    switch (r) {
    case HV_SUCCESS:        return "HV_SUCCESS";
    case HV_ERROR:          return "HV_ERROR (generic)";
    case HV_BUSY:           return "HV_BUSY";
    case HV_BAD_ARGUMENT:   return "HV_BAD_ARGUMENT";
    case HV_NO_RESOURCES:   return "HV_NO_RESOURCES";
    case HV_NO_DEVICE:      return "HV_NO_DEVICE (没有可用的 hypervisor 设备)";
    case HV_UNSUPPORTED:    return "HV_UNSUPPORTED (这台机器不支持)";
    default:                return "(未知)";
    }
}

int main(void)
{
    puts("=== sysctl ===");
    read_sysctl_int("kern.hv_support");
    read_sysctl_int("kern.hv_vmm_present");

    puts("\n=== hv_vm_create(HV_VM_DEFAULT) ===");
    hv_return_t r = hv_vm_create(HV_VM_DEFAULT);
    printf("  返回 0x%08x  %s\n", (unsigned)r, hv_err(r));

    if (r != HV_SUCCESS) {
        puts("\n>>> 判定：**嵌套虚拟化不可用。**");
        puts(">>>   HV_UNSUPPORTED / HV_NO_DEVICE → KVM 宿主没开嵌套，或 VMX 没透传。");
        puts(">>>   HV_ERROR 且 sysctl 都是 1 → 更可能是 entitlement 没生效，");
        puts(">>>   先确认 codesign -d --entitlements 能看到 com.apple.security.hypervisor。");
        return 1;
    }

    /* 再往前走一步：分配一段 guest 物理内存并映射。
     * hv_vm_create 成功只说明拿到了 VM 句柄；能 map 才说明 EPT 真的可用。 */
    puts("\n=== hv_vm_map(2 MiB) ===");
    const size_t sz = 2u << 20;
    void *mem = valloc(sz);
    if (mem == NULL) {
        puts("  valloc 失败");
        hv_vm_destroy();
        return 2;
    }
    memset(mem, 0, sz);
    r = hv_vm_map(mem, 0, sz, HV_MEMORY_READ | HV_MEMORY_WRITE | HV_MEMORY_EXEC);
    printf("  返回 0x%08x  %s\n", (unsigned)r, hv_err(r));
    if (r != HV_SUCCESS) {
        puts("\n>>> VM 建出来了但内存映射失败 —— EPT 不可用，实际跑不了 guest。");
        free(mem);
        hv_vm_destroy();
        return 1;
    }

    /* 第三步：建一个 vCPU。到这一步成功，QEMU 的 -accel hvf 基本就能用。 */
    puts("\n=== hv_vcpu_create ===");
    hv_vcpuid_t vcpu = 0;
    r = hv_vcpu_create(&vcpu, HV_VCPU_DEFAULT);
    printf("  返回 0x%08x  %s  vcpuid=%llu\n",
           (unsigned)r, hv_err(r), (unsigned long long)vcpu);
    if (r == HV_SUCCESS) {
        hv_vcpu_destroy(vcpu);
        puts("\n>>> 判定：**嵌套虚拟化可用。** VM + 内存映射 + vCPU 三步全过。");
        puts(">>>   下一步可以用 QEMU 的 -accel hvf 在运行器里启动造出来的盘，");
        puts(">>>   V-025（自建盘能不能引导）因此可以在 CI 内部关闭。");
    } else {
        puts("\n>>> VM 与内存都成了但 vCPU 建不出来。");
    }

    hv_vm_unmap(0, sz);
    free(mem);
    hv_vm_destroy();
    return r == HV_SUCCESS ? 0 : 1;
}
