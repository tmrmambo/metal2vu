// 核对 30 分册第 3 节的 data layout 断言：`v96:128:128` 使 float3 占 16 字节。
// 这条断言决定 40 分册里 buffer 布局的转译规则，错了会导致全部
// 结构体成员偏移错位。编译后用 metal-objdump 看 datalayout 字符串，
// 并用 sizeof 的编译期断言直接证伪。
#include <metal_stdlib>
using namespace metal;

struct Packed { packed_float3 a; float b; };          // 期望 16
struct Plain  { float3 a; float b; };                 // 期望 32（a 占 16，b 对齐到 16）
struct Mixed  { float2 a; float3 b; float c; };
struct Half3  { half3 a; half b; };

static_assert(sizeof(float3)  == 16, "float3 must occupy 16 bytes");
static_assert(alignof(float3) == 16, "float3 must align to 16");
static_assert(sizeof(Packed)  == 16, "packed_float3+float must be 16");
static_assert(sizeof(Plain)   == 32, "float3+float must be 32");
static_assert(sizeof(half3)   == 8,  "half3 must occupy 8 bytes");

kernel void k_layout(device uint *out [[buffer(0)]],
                     constant Plain  &p [[buffer(1)]],
                     constant Packed &q [[buffer(2)]],
                     constant Mixed  &m [[buffer(3)]],
                     constant Half3  &h [[buffer(4)]],
                     uint tid [[thread_position_in_grid]]) {
    out[0] = sizeof(Plain);
    out[1] = sizeof(Packed);
    out[2] = sizeof(Mixed);
    out[3] = sizeof(Half3);
    out[4] = sizeof(float3);
    out[5] = alignof(float3);
    out[6] = (uint)(p.b + q.b + m.c + (float)h.b) + tid * 0;
}
