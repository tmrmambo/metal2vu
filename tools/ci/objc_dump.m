// Metal.framework 的 ObjC 运行期转储器。
//
// 目的：把 docs/spec/20-OBJC-DEVICE.md、21-OBJC-OBJECT-FAMILY.md、
// 22-OBJC-DESCRIPTORS.md 里**由静态分析推出**的 selector 表、继承链、
// 协议条目数与 ivar 布局，拿运行期的权威答案核对一遍。
//
// 它补上一件静态转储没有的东西：**method type encoding**。
// analysis/.../metal-objc.json 是 class-dump 式的转储，没有 encoding，
// 所以每个方法的参数与返回类型此前只能靠反汇编推断。
//
// 输出是 JSON，写到 stdout。不输出任何 Apple 二进制内容，只输出
// 运行期可自省的元数据（类名、方法名、encoding、ivar 偏移）。

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#import <objc/Protocol.h>
#import <dlfcn.h>

static NSString *JStr(const char *s) {
    if (!s) return @"";
    return [NSString stringWithUTF8String:s] ?: @"";
}

// ---- 我们关心的类。覆盖 20/21/22 三册的承重节点。 ----
static const char *kClasses[] = {
    // 20 分册：device 节点与其父类
    "MTLIOAccelDevice", "_MTLDevice", "MTLDevice",
    // 官方半虚拟化驱动的 device（若运行器本身是虚机，这个类会被注册）
    "AppleParavirtDevice",
    // 21 分册：七个 MTLIOAccel* 节点
    "MTLIOAccelCommandQueue", "MTLIOAccelCommandBuffer",
    "MTLIOAccelBuffer", "MTLIOAccelTexture",
    "MTLIOAccelPooledResource", "MTLIOAccelHeap",
    // 21 分册：encoder 与 state 走 _MTL* 抽象层
    "_MTLCommandQueue", "_MTLCommandBuffer", "_MTLBuffer", "_MTLTexture",
    "_MTLRenderCommandEncoder", "_MTLComputeCommandEncoder",
    "_MTLBlitCommandEncoder", "_MTLParallelRenderCommandEncoder",
    "_MTLRenderPipelineState", "_MTLComputePipelineState",
    "_MTLDepthStencilState", "_MTLSamplerState",
    "_MTLLibrary", "_MTLFunction", "_MTLHeap", "_MTLFence", "_MTLEvent",
    // 22 分册：descriptor 族的代表
    "MTLRenderPipelineDescriptor", "MTLComputePipelineDescriptor",
    "MTLTextureDescriptor", "MTLSamplerDescriptor",
    "MTLDepthStencilDescriptor", "MTLRenderPassDescriptor",
    "MTLRenderPassColorAttachmentDescriptor",
    "MTLRenderPipelineColorAttachmentDescriptor",
    "MTLVertexDescriptor", "MTLHeapDescriptor", "MTLCompileOptions",
    // 32 分册：编译器入口
    "MTLCompiler", "MTLLibraryBuilder", "MTLLibraryDataWithArchive",
    NULL
};

// ---- 我们关心的协议。用来核实 427 required + 80 optional = 507。 ----
static const char *kProtocols[] = {
    "MTLDevice", "MTLDeviceSPI",
    "MTLCommandQueue", "MTLCommandQueueSPI",
    "MTLCommandBuffer", "MTLCommandBufferSPI",
    "MTLBuffer", "MTLTexture", "MTLResource", "MTLResourceSPI",
    "MTLLibrary", "MTLFunction", "MTLFunctionSPI",
    "MTLRenderPipelineState", "MTLComputePipelineState",
    "MTLRenderCommandEncoder", "MTLComputeCommandEncoder",
    "MTLBlitCommandEncoder", "MTLCommandEncoder",
    "MTLHeap", "MTLFence", "MTLEvent", "MTLSharedEvent",
    "MTLDrawable", "MTLIOCommandQueue",
    NULL
};

static NSArray *DumpMethods(Class cls, BOOL meta) {
    unsigned int n = 0;
    Method *ms = class_copyMethodList(meta ? object_getClass((id)cls) : cls, &n);
    NSMutableArray *out = [NSMutableArray arrayWithCapacity:n];
    for (unsigned int i = 0; i < n; i++) {
        [out addObject:@{
            @"sel"  : JStr(sel_getName(method_getName(ms[i]))),
            @"enc"  : JStr(method_getTypeEncoding(ms[i])),
            @"argc" : @(method_getNumberOfArguments(ms[i])),
        }];
    }
    if (ms) free(ms);
    [out sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        return [a[@"sel"] compare:b[@"sel"]];
    }];
    return out;
}

static NSArray *DumpIvars(Class cls) {
    unsigned int n = 0;
    Ivar *vs = class_copyIvarList(cls, &n);
    NSMutableArray *out = [NSMutableArray arrayWithCapacity:n];
    for (unsigned int i = 0; i < n; i++) {
        [out addObject:@{
            @"name"   : JStr(ivar_getName(vs[i])),
            @"enc"    : JStr(ivar_getTypeEncoding(vs[i])),
            @"offset" : @(ivar_getOffset(vs[i])),
        }];
    }
    if (vs) free(vs);
    return out;
}

static NSArray *DumpAdoptedProtocols(Class cls) {
    unsigned int n = 0;
    Protocol * __unsafe_unretained *ps = class_copyProtocolList(cls, &n);
    NSMutableArray *out = [NSMutableArray arrayWithCapacity:n];
    for (unsigned int i = 0; i < n; i++)
        [out addObject:JStr(protocol_getName(ps[i]))];
    if (ps) free(ps);
    return [out sortedArrayUsingSelector:@selector(compare:)];
}

static NSArray *DumpSuperchain(Class cls) {
    NSMutableArray *out = [NSMutableArray array];
    for (Class c = class_getSuperclass(cls); c; c = class_getSuperclass(c))
        [out addObject:JStr(class_getName(c))];
    return out;
}

static NSDictionary *DumpProtocolDescs(Protocol *p, BOOL required, BOOL instance) {
    unsigned int n = 0;
    struct objc_method_description *ds =
        protocol_copyMethodDescriptionList(p, required, instance, &n);
    NSMutableArray *out = [NSMutableArray arrayWithCapacity:n];
    for (unsigned int i = 0; i < n; i++) {
        [out addObject:@{
            @"sel" : JStr(sel_getName(ds[i].name)),
            @"enc" : JStr(ds[i].types),
        }];
    }
    if (ds) free(ds);
    [out sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        return [a[@"sel"] compare:b[@"sel"]];
    }];
    return @{ @"count" : @(n), @"methods" : out };
}

int main(void) { @autoreleasepool {
    NSMutableDictionary *root = [NSMutableDictionary dictionary];
    root[@"schema"] = @"metal2vu/objc-runtime-dump/1";

    // 先强制 Metal 初始化一次，让厂商驱动 bundle 被加载、其类被注册。
    // 这一步本身就是证据：运行器上实际枚举到什么 device。
    NSMutableArray *devs = [NSMutableArray array];
    @try {
        NSArray<id<MTLDevice>> *all = MTLCopyAllDevices();
        for (id<MTLDevice> d in all) {
            Class dc = [(NSObject *)d class];
            [devs addObject:@{
                @"name"        : d.name ?: @"",
                @"class"       : JStr(class_getName(dc)),
                @"superchain"  : DumpSuperchain(dc),
                @"registryID"  : @(d.registryID),
                @"lowPower"    : @(d.isLowPower),
                @"removable"   : @(d.isRemovable),
                @"headless"    : @(d.isHeadless),
                @"unifiedMem"  : @(d.hasUnifiedMemory),
                @"maxBufLen"   : @(d.maxBufferLength),
                @"argBufTier"  : @(d.argumentBuffersSupport),
                // 60 分册关心的 family 声明
                @"famApple9"   : @([d supportsFamily:(MTLGPUFamily)1009]),
                @"famMac2"     : @([d supportsFamily:MTLGPUFamilyMac2]),
                @"famMetal3"   : @([d supportsFamily:(MTLGPUFamily)5001]),
                @"famMetal4"   : @([d supportsFamily:(MTLGPUFamily)5002]),
            }];
        }
    } @catch (NSException *e) {
        [devs addObject:@{ @"error" : e.reason ?: @"unknown" }];
    }
    root[@"devices"] = devs;

    // 加载过的 Metal 相关镜像（看厂商 bundle 实际从哪来）
    NSMutableArray *imgs = [NSMutableArray array];
    unsigned int ic = 0;
    const char **names = objc_copyImageNames(&ic);
    for (unsigned int i = 0; i < ic; i++) {
        NSString *s = JStr(names[i]);
        if ([s containsString:@"Metal"] || [s containsString:@"GPU"] ||
            [s containsString:@"Accelerat"] || [s containsString:@"Paravirt"] ||
            [s containsString:@"AGX"] || [s containsString:@"Compiler"])
            [imgs addObject:s];
    }
    if (names) free((void *)names);
    root[@"metal_images"] = [imgs sortedArrayUsingSelector:@selector(compare:)];

    // 类转储
    NSMutableDictionary *classes = [NSMutableDictionary dictionary];
    for (int i = 0; kClasses[i]; i++) {
        Class c = objc_getClass(kClasses[i]);
        if (!c) { classes[JStr(kClasses[i])] = @{ @"present" : @NO }; continue; }
        classes[JStr(kClasses[i])] = @{
            @"present"        : @YES,
            @"instanceSize"   : @(class_getInstanceSize(c)),
            @"superchain"     : DumpSuperchain(c),
            @"protocols"      : DumpAdoptedProtocols(c),
            @"ivars"          : DumpIvars(c),
            @"instanceMethods": DumpMethods(c, NO),
            @"classMethods"   : DumpMethods(c, YES),
        };
    }
    root[@"classes"] = classes;

    // 协议转储
    NSMutableDictionary *protos = [NSMutableDictionary dictionary];
    for (int i = 0; kProtocols[i]; i++) {
        Protocol *p = objc_getProtocol(kProtocols[i]);
        if (!p) { protos[JStr(kProtocols[i])] = @{ @"present" : @NO }; continue; }
        NSDictionary *ri = DumpProtocolDescs(p, YES, YES);
        NSDictionary *oi = DumpProtocolDescs(p, NO,  YES);
        NSDictionary *rc = DumpProtocolDescs(p, YES, NO);
        NSDictionary *oc = DumpProtocolDescs(p, NO,  NO);
        unsigned int np = 0;
        Protocol * __unsafe_unretained *parents = protocol_copyProtocolList(p, &np);
        NSMutableArray *pl = [NSMutableArray array];
        for (unsigned int k = 0; k < np; k++) [pl addObject:JStr(protocol_getName(parents[k]))];
        if (parents) free(parents);
        protos[JStr(kProtocols[i])] = @{
            @"present"           : @YES,
            @"inherits"          : pl,
            @"requiredInstance"  : ri,
            @"optionalInstance"  : oi,
            @"requiredClass"     : rc,
            @"optionalClass"     : oc,
            @"totalRequired"     : @([ri[@"count"] unsignedIntValue] + [rc[@"count"] unsignedIntValue]),
            @"totalOptional"     : @([oi[@"count"] unsignedIntValue] + [oc[@"count"] unsignedIntValue]),
        };
    }
    root[@"protocols"] = protos;

    NSError *err = nil;
    NSData *j = [NSJSONSerialization dataWithJSONObject:root
                                               options:NSJSONWritingPrettyPrinted |
                                                       NSJSONWritingSortedKeys
                                                 error:&err];
    if (!j) { fprintf(stderr, "json error: %s\n", err.description.UTF8String); return 1; }
    fwrite(j.bytes, 1, j.length, stdout);
    fputc('\n', stdout);
    return 0;
}}
