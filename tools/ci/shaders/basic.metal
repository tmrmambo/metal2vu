// 最小 vertex + fragment。30 分册第 4 节的 air.vertex / air.fragment
// named metadata 与 ParamRole/Builtin/OutputRole 清单的基准样本。
#include <metal_stdlib>
using namespace metal;

struct VIn  { float4 pos [[attribute(0)]]; float2 uv [[attribute(1)]]; };
struct VOut { float4 pos [[position]]; float2 uv; };

vertex VOut v_main(VIn in [[stage_in]],
                   constant float4x4 &mvp [[buffer(0)]],
                   uint vid [[vertex_id]],
                   uint iid [[instance_id]]) {
    VOut o;
    o.pos = mvp * in.pos;
    o.uv  = in.uv + float2(vid & 1, iid & 1) * 0.0;
    return o;
}

fragment float4 f_main(VOut in [[stage_in]],
                       bool front [[front_facing]],
                       float2 pc  [[point_coord]]) {
    return float4(in.uv, front ? 1.0 : 0.0, pc.x * 0.0 + 1.0);
}
