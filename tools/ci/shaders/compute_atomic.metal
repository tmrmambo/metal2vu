// compute + atomics + threadgroup 内存 + barrier。
// 60 分册认定 compute 是 WindowServer 首帧 19 项最小集里的必需项。
#include <metal_stdlib>
using namespace metal;

kernel void k_reduce(device const float   *src [[buffer(0)]],
                     device atomic_uint   *acc [[buffer(1)]],
                     device float         *dst [[buffer(2)]],
                     threadgroup float    *tg  [[threadgroup(0)]],
                     uint  tid  [[thread_position_in_grid]],
                     uint  ltid [[thread_position_in_threadgroup]],
                     uint  tgsz [[threads_per_threadgroup]]) {
    tg[ltid] = src[tid];
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for (uint s = tgsz / 2; s > 0; s >>= 1) {
        if (ltid < s) tg[ltid] += tg[ltid + s];
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    if (ltid == 0) {
        dst[tid / tgsz] = tg[0];
        atomic_fetch_add_explicit(acc, (uint)tg[0], memory_order_relaxed);
    }
}

kernel void k_atomics(device atomic_uint *u [[buffer(0)]],
                      device atomic_int  *i [[buffer(1)]],
                      uint tid [[thread_position_in_grid]]) {
    atomic_fetch_or_explicit (u, 1u << (tid & 31), memory_order_relaxed);
    atomic_fetch_and_explicit(u, ~0u,              memory_order_relaxed);
    atomic_fetch_xor_explicit(u, tid,              memory_order_relaxed);
    atomic_fetch_min_explicit(i, (int)tid,         memory_order_relaxed);
    atomic_fetch_max_explicit(i, (int)tid,         memory_order_relaxed);
    uint expected = tid;
    atomic_compare_exchange_weak_explicit(u, &expected, tid + 1,
                                          memory_order_relaxed,
                                          memory_order_relaxed);
}
