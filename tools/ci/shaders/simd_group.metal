// SIMD/quad group 操作。60 分册记录 Metal 侧 subgroup 宽度是 32，
// 而 Lavapipe 是 4/8，这是能力矩阵里一处确定的不匹配。本样本用来
// 取得这些操作在 AIR 里的 intrinsic 名，供 30/40 分册做转译映射。
#include <metal_stdlib>
using namespace metal;

kernel void k_simd(device float *out [[buffer(0)]],
                   device const float *in [[buffer(1)]],
                   uint tid  [[thread_position_in_grid]],
                   uint lane [[thread_index_in_simdgroup]],
                   uint sgsz [[threads_per_simdgroup]],
                   uint sgid [[simdgroup_index_in_threadgroup]]) {
    float v = in[tid];
    float s = simd_sum(v);
    float m = simd_max(v);
    float n = simd_min(v);
    float p = simd_prefix_exclusive_sum(v);
    float b = simd_broadcast(v, 0);
    float f = simd_shuffle(v, lane ^ 1);
    float u = simd_shuffle_up(v, 1);
    float d = simd_shuffle_down(v, 1);
    bool  a = simd_all(v > 0.0f);
    bool  y = simd_any(v > 0.0f);
    uint64_t ballot = (uint64_t)simd_ballot(v > 0.0f);

    float q = quad_sum(v);
    float qb = quad_broadcast(v, 0);

    out[tid] = s + m + n + p + b + f + u + d + q + qb
             + (a ? 1.0f : 0.0f) + (y ? 2.0f : 0.0f)
             + (float)(ballot & 1) + (float)sgsz + (float)sgid;
}
