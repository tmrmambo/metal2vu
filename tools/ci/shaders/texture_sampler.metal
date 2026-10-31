// 纹理与采样器的各种形态，含 array / cube / MS / depth / 可写。
// 12 分册（IOSurface）与 40 分册的格式映射都需要知道这些在 AIR
// 里的类型表示。
#include <metal_stdlib>
using namespace metal;

struct VOut { float4 pos [[position]]; float3 uvw; };

vertex VOut v_tex(uint vid [[vertex_id]]) {
    const float2 q[3] = { float2(-1,-1), float2(3,-1), float2(-1,3) };
    VOut o; o.pos = float4(q[vid], 0, 1); o.uvw = float3(q[vid] * 0.5 + 0.5, 0); return o;
}

fragment float4 f_tex(VOut in [[stage_in]],
                      texture2d<float>        t2  [[texture(0)]],
                      texture2d_array<float>  t2a [[texture(1)]],
                      texture3d<float>        t3  [[texture(2)]],
                      texturecube<float>      tc  [[texture(3)]],
                      texture2d_ms<float>     tms [[texture(4)]],
                      depth2d<float>          td  [[texture(5)]],
                      texture2d<half>         th  [[texture(6)]],
                      texture2d<uint>         tu  [[texture(7)]],
                      sampler                 s   [[sampler(0)]],
                      sampler                 sc  [[sampler(1)]]) {
    float4 a = t2.sample(s, in.uvw.xy);
    float4 b = t2a.sample(s, in.uvw.xy, 0);
    float4 c = t3.sample(s, in.uvw);
    float4 d = tc.sample(s, normalize(in.uvw * 2.0 - 1.0));
    float4 e = tms.read(uint2(in.pos.xy), 0);
    float  g = td.sample_compare(sc, in.uvw.xy, 0.5);
    float4 h = (float4)th.sample(s, in.uvw.xy);
    float4 i = (float4)tu.read(uint2(in.pos.xy));
    float4 j = t2.gather(s, in.uvw.xy);
    float4 k = t2.sample(s, in.uvw.xy, level(1.0));
    float4 l = t2.sample(s, in.uvw.xy, bias(0.5));
    float4 m = t2.sample(s, in.uvw.xy, gradient2d(float2(0.01), float2(0.01)));
    return a + b + c + d + e + float4(g) + h + i + j + k + l + m;
}

kernel void k_write(texture2d<float, access::write>      w  [[texture(0)]],
                    texture2d<float, access::read_write> rw [[texture(1)]],
                    uint2 gid [[thread_position_in_grid]]) {
    float4 v = rw.read(gid);
    rw.write(v * 2.0, gid);
    w.write(v, gid);
}
