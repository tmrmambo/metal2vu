// Framebuffer fetch。60 分册认定这是 WindowServer 登录路径就会命中的
// 特性，而上游 metal2vulkan 有 24 处拒绝点；它也是三个最严重上游缺口
// 之一。本样本用来取得 fetch 在 AIR 里的真实表示（输入是带 [[color(n)]]
// 的 fragment 参数，不是纹理读取），以及 60 分册点名的私有像素格式
// RGB10A8_2P_XR10 在 MSL 侧是否可达。
#include <metal_stdlib>
using namespace metal;

struct VOut { float4 pos [[position]]; };

vertex VOut v_fb(uint vid [[vertex_id]]) {
    const float2 q[3] = { float2(-1,-1), float2(3,-1), float2(-1,3) };
    VOut o; o.pos = float4(q[vid], 0, 1); return o;
}

// 单附件 fetch
fragment float4 f_fetch1(float4 prev [[color(0)]]) {
    return prev * 0.5 + float4(0.25);
}

// 多附件 fetch，核对 maxColorAttachments 路径
struct FetchIn {
    float4 c0 [[color(0)]];
    float4 c1 [[color(1)]];
    half4  c2 [[color(2)]];
};
struct FetchOut {
    float4 c0 [[color(0)]];
    float4 c1 [[color(1)]];
    half4  c2 [[color(2)]];
};
fragment FetchOut f_fetchN(FetchIn in [[stage_in]]) {
    FetchOut o;
    o.c0 = in.c0 + in.c1;
    o.c1 = in.c1 - in.c0;
    o.c2 = in.c2 * half4(2.0h);
    return o;
}

// 显式 depth 写出（不是 fetch）。与上面分开，避免一个构造出错
// 把整个文件的产物带掉。
struct DOut { float4 c [[color(0)]]; float d [[depth(any)]]; };
fragment DOut f_depthWrite(VOut in [[stage_in]], float4 prev [[color(0)]]) {
    DOut o; o.c = prev; o.d = in.pos.z * 0.5; return o;
}
