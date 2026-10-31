// 建一条真实的 render pipeline 与一条 compute pipeline，强制 Metal 走
// compiler plugin 那条路，使 tools/ci/airdump/interpose.c 能拦到实参。
//
// 规格：docs/spec/32-COMPILER-PLUGIN.md
//
// 关键：必须用 `newLibraryWithData:`（metallib 字节）而不是
// `newLibraryWithSource:`。`20`/`21` 分册确证 APV 对 source 路径零 IMP，
// 而且上游 metal2vulkan 也只接受 metallib（`42` 分册）。source 路径会走
// 另一条编译链，拦不到我们要的那个入口。

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

static int fail(NSString *msg, NSError *err) {
    fprintf(stderr, "FAIL: %s%s%s\n", msg.UTF8String,
            err ? " :: " : "", err ? err.localizedDescription.UTF8String : "");
    return 1;
}

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <metallib path> [more.metallib ...]\n", argv[0]);
        return 2;
    }

    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    if (!dev) return fail(@"no Metal device", nil);
    fprintf(stderr, "device: %s (%s)\n",
            dev.name.UTF8String,
            NSStringFromClass([(NSObject *)dev class]).UTF8String);

    for (int i = 1; i < argc; i++) {
        NSString *path = [NSString stringWithUTF8String:argv[i]];
        NSData *data = [NSData dataWithContentsOfFile:path];
        if (!data) { fprintf(stderr, "skip (unreadable): %s\n", argv[i]); continue; }
        fprintf(stderr, "\n==== %s (%lu bytes) ====\n", argv[i],
                (unsigned long)data.length);

        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithData:data error:&err];
        if (!lib) { fail(@"newLibraryWithData:", err); continue; }
        fprintf(stderr, "functions: %s\n",
                [[lib.functionNames componentsJoinedByString:@", "] UTF8String]);

        // ---- render pipeline：需要一个 vertex + 一个 fragment ----
        id<MTLFunction> vfn = nil, ffn = nil, kfn = nil;
        for (NSString *n in lib.functionNames) {
            id<MTLFunction> f = [lib newFunctionWithName:n];
            if (!f) continue;
            if (f.functionType == MTLFunctionTypeVertex   && !vfn) vfn = f;
            if (f.functionType == MTLFunctionTypeFragment && !ffn) ffn = f;
            if (f.functionType == MTLFunctionTypeKernel   && !kfn) kfn = f;
        }

        if (vfn && ffn) {
            MTLRenderPipelineDescriptor *rpd = [MTLRenderPipelineDescriptor new];
            rpd.vertexFunction   = vfn;
            rpd.fragmentFunction = ffn;
            rpd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
            err = nil;
            id<MTLRenderPipelineState> rps =
                [dev newRenderPipelineStateWithDescriptor:rpd error:&err];
            fprintf(stderr, "render pipeline: %s\n",
                    rps ? "OK" : err.localizedDescription.UTF8String);
        } else {
            fprintf(stderr, "render pipeline: skipped (no vertex+fragment pair)\n");
        }

        if (kfn) {
            err = nil;
            id<MTLComputePipelineState> cps =
                [dev newComputePipelineStateWithFunction:kfn error:&err];
            fprintf(stderr, "compute pipeline: %s\n",
                    cps ? "OK" : err.localizedDescription.UTF8String);
        } else {
            fprintf(stderr, "compute pipeline: skipped (no kernel)\n");
        }
    }

    fprintf(stderr, "\ndone\n");
    return 0;
}}
