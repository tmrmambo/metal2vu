// Argument buffer。20 分册确证 APV 的 argumentBuffersSupport 返回 0
// （Tier1），而本项目也打算报 Tier1。本样本取 Tier1 可用形态在 AIR
// 里的表示，并验证 Tier2 构造在编译期是否就被拒。
#include <metal_stdlib>
using namespace metal;

// Tier1：argument buffer 内只放资源与常量，索引必须是编译期常量
struct Args1 {
    texture2d<float>  tex   [[id(0)]];
    sampler           samp  [[id(1)]];
    device float     *buf   [[id(2)]];
    float4            tint  [[id(3)]];
    uint              count [[id(4)]];
};

fragment float4 f_arg1(float4 pos [[position]],
                       constant Args1 &a [[buffer(0)]]) {
    float2 uv = pos.xy * 0.001;
    return a.tex.sample(a.samp, uv) * a.tint + a.buf[0] + (float)a.count * 0.0;
}

// 嵌套 argument buffer，Tier1 的边界情形
struct Inner { device float *p [[id(0)]]; uint n [[id(1)]]; };
struct Outer { constant Inner *inner [[id(0)]]; texture2d<float> t [[id(1)]]; };

kernel void k_arg_nested(constant Outer &o [[buffer(0)]],
                         device float *out [[buffer(1)]],
                         uint tid [[thread_position_in_grid]]) {
    out[tid] = o.inner[0].p[0] + (float)o.inner[0].n;
}

// 常量数组形式的资源绑定（Tier1 允许固定长度数组）
struct ArgArray {
    array<texture2d<float>, 4> texs [[id(0)]];
    array<sampler, 2>          samps [[id(4)]];
};

fragment float4 f_arg_array(float4 pos [[position]],
                            constant ArgArray &a [[buffer(0)]]) {
    float2 uv = pos.xy * 0.001;
    return a.texs[0].sample(a.samps[0], uv)
         + a.texs[1].sample(a.samps[1], uv)
         + a.texs[2].sample(a.samps[0], uv)
         + a.texs[3].sample(a.samps[1], uv);
}
