/* 拦 Metal compiler plugin 的入口，把它收到的两个输入原样 dump 下来。
 *
 * 目的：关掉 docs/spec/32-COMPILER-PLUGIN.md 第 8 节的空白 ——
 * `MTLCompilerBuildRequestWithSerializedBitcode` 的第二个输入是一个
 * FlatBuffers 描述（identifier `AIRF` / `AIRP`，命名空间 `Air` / `Mtl4`），
 * 但它的 schema 至今没有任何证据。
 *
 * 为什么现在能做：
 *   - `91-RUNTIME-EVIDENCE.md` 第 1 节确证 macos-26-intel 运行器本身就是
 *     一台 KVM guest，GPU 是 AppleParavirtGPU，**SIP 已关闭**；
 *   - 我们注入的是**自己的** ad-hoc 签名可执行文件，不是平台二进制，
 *     所以 `DYLD_INSERT_LIBRARIES` 生效（SIP 关着则更无障碍）；
 *   - plugin 是被 `MTLCompiler.framework` 用 dlopen + dlsym 取的
 *     （`32` 第 2 节的三跳加载链），所以拦 `dlsym` 就能换掉函数指针。
 *
 * 为什么拦 dlsym 而不是直接 interpose 那个符号：
 *   plugin 在 dyld shared cache 里、而且是运行时才被 dlopen 的，
 *   `__DATA,__interpose` 对尚未加载的镜像里的符号无效。
 *
 * 关于签名：
 *   `32` 分册只确证了它收 AIR bitcode 的**原始字节**（`const void*, size_t`）
 *   加一个 FlatBuffers 描述，**参数个数与顺序未确证**。所以这里不假定签名：
 *   按 6 个 word 收，逐个当候选指针探测，谁看起来像 AIR、谁看起来像
 *   FlatBuffers 就 dump 谁。这样不知道签名也能拿到数据。
 */

#include <dlfcn.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>

#define OUTDIR_ENV "AIRDUMP_OUT"
#define MAX_DUMPS  64

static int   g_dumps = 0;
static char  g_outdir[1024] = "/tmp/airdump";

static void ensure_outdir(void) {
    const char *e = getenv(OUTDIR_ENV);
    if (e && *e) snprintf(g_outdir, sizeof g_outdir, "%s", e);
    mkdir(g_outdir, 0755);
}

/* 判断一个地址是否可读，且返回该区域剩余可读字节数上界。
 * 用 mach_vm_region 而不是 try/catch：在被拦的回调里崩掉会毁掉整次采集。 */
static size_t readable_span(const void *p) {
    if (!p) return 0;
    mach_vm_address_t addr = (mach_vm_address_t)(uintptr_t)p;
    mach_vm_size_t    size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t cnt = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t obj = MACH_PORT_NULL;
    mach_vm_address_t a = addr;
    if (mach_vm_region(mach_task_self(), &a, &size, VM_REGION_BASIC_INFO_64,
                       (vm_region_info_t)&info, &cnt, &obj) != KERN_SUCCESS)
        return 0;
    if (a > addr) return 0;                       /* 落在区域之前 */
    if (!(info.protection & VM_PROT_READ)) return 0;
    mach_vm_address_t end = a + size;
    if (addr >= end) return 0;
    return (size_t)(end - addr);
}

static void write_blob(const char *tag, int idx, const void *p, size_t n) {
    char path[1200];
    snprintf(path, sizeof path, "%s/%s-%03d.bin", g_outdir, tag, idx);
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fwrite(p, 1, n, f);
    fclose(f);
    fprintf(stderr, "[airdump] wrote %s (%zu bytes)\n", path, n);
}

static void note(const char *fmt, ...) {
    char path[1200];
    snprintf(path, sizeof path, "%s/NOTES.txt", g_outdir);
    FILE *f = fopen(path, "a");
    if (!f) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fclose(f);
}

/* AIR 的两种头：`91` 第 3 节实测 `xcrun metal -c` 产出的是
 * 0x0B17C0DE wrapper（小端字节序 de c0 17 0b）；裸 bitcode 是 'BC' 0xC0DE。 */
static int looks_like_air(const uint8_t *b, size_t n) {
    if (n < 4) return 0;
    uint32_t m = (uint32_t)b[0] | ((uint32_t)b[1] << 8)
               | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
    if (m == 0x0B17C0DEu) return 1;
    if (b[0] == 'B' && b[1] == 'C' && b[2] == 0xC0 && b[3] == 0xDE) return 1;
    if (n >= 4 && memcmp(b, "MTLB", 4) == 0) return 1;
    return 0;
}

/* FlatBuffers 的布局：前 4 字节是到 root table 的 uoffset，
 * 紧跟 4 字节 file_identifier。`32` 第 8 节说 identifier 是 AIRF / AIRP。 */
static const char *looks_like_flatbuffer(const uint8_t *b, size_t n) {
    if (n < 8) return NULL;
    uint32_t root = (uint32_t)b[0] | ((uint32_t)b[1] << 8)
                  | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
    if (root < 4 || root > n) return NULL;            /* root offset 不合理 */
    static char id[5];
    memcpy(id, b + 4, 4);
    id[4] = 0;
    for (int i = 0; i < 4; i++)
        if (id[i] < 0x20 || id[i] > 0x7E) return NULL; /* identifier 必须可打印 */
    return id;
}

typedef void *(*build_fn)(void *, void *, void *, void *, void *, void *);
static build_fn g_real_build = NULL;

static void *wrap_build(void *a0, void *a1, void *a2,
                        void *a3, void *a4, void *a5) {
    int idx = g_dumps++;
    void *args[6] = { a0, a1, a2, a3, a4, a5 };

    note("\n=== call #%d MTLCompilerBuildRequestWithSerializedBitcode ===\n", idx);
    for (int i = 0; i < 6; i++) {
        size_t span = readable_span(args[i]);
        note("  arg[%d] = %p  readable_span=%zu", i, args[i], span);
        if (span == 0) {
            /* 不是指针就当标量看，很可能是那个 size_t 长度 */
            note("   (scalar? %llu)\n", (unsigned long long)(uintptr_t)args[i]);
            continue;
        }
        const uint8_t *b = (const uint8_t *)args[i];
        size_t take = span < (1u << 22) ? span : (1u << 22);   /* 上限 4 MiB */

        if (looks_like_air(b, take)) {
            note("   -> AIR-like\n");
            /* 若相邻参数是合理长度就用它，否则按 span 截断 */
            size_t len = take;
            for (int j = 0; j < 6; j++) {
                uintptr_t v = (uintptr_t)args[j];
                if (readable_span(args[j]) == 0 && v > 16 && v <= take) { len = v; break; }
            }
            char tag[64]; snprintf(tag, sizeof tag, "air-a%d", i);
            write_blob(tag, idx, b, len);
            note("   dumped %zu bytes as AIR\n", len);
            continue;
        }
        const char *fid = looks_like_flatbuffer(b, take);
        if (fid) {
            note("   -> FlatBuffers-like, file_identifier=\"%s\"\n", fid);
            size_t len = take < 65536 ? take : 65536;
            char tag[64]; snprintf(tag, sizeof tag, "flatbuf-a%d", i);
            write_blob(tag, idx, b, len);
            note("   dumped %zu bytes as FlatBuffers\n", len);
            continue;
        }
        /* 认不出来也存头部，留给离线分析 */
        note("   -> unknown; first 32 bytes:");
        for (size_t k = 0; k < 32 && k < take; k++) note(" %02X", b[k]);
        note("\n");
        size_t len = take < 4096 ? take : 4096;
        char tag[64]; snprintf(tag, sizeof tag, "unknown-a%d", i);
        write_blob(tag, idx, b, len);
    }

    if (!g_real_build) { note("  !! real fn missing, returning NULL\n"); return NULL; }
    if (g_dumps > MAX_DUMPS) { /* 够了就别再写文件，但仍要转发 */ }
    return g_real_build(a0, a1, a2, a3, a4, a5);
}

/* ---- dlsym 拦截 ---- */

static void *(*real_dlsym)(void *, const char *) = NULL;

void *my_dlsym(void *handle, const char *symbol) {
    if (!real_dlsym) {
        /* RTLD_NEXT 拿到链上的下一个 dlsym，即真正的那个 */
        real_dlsym = (void *(*)(void *, const char *))
            dlsym(RTLD_NEXT, "dlsym");
    }
    void *r = real_dlsym ? real_dlsym(handle, symbol) : NULL;

    if (symbol && strcmp(symbol, "MTLCompilerBuildRequestWithSerializedBitcode") == 0) {
        ensure_outdir();
        note("[airdump] dlsym(%p, \"%s\") -> %p   (intercepting)\n",
             handle, symbol, r);
        Dl_info di;
        if (r && dladdr(r, &di))
            note("[airdump]   provider image: %s\n",
                 di.dli_fname ? di.dli_fname : "?");
        g_real_build = (build_fn)r;
        return (void *)wrap_build;
    }

    /* 顺便把 plugin 相关的 dlsym 都记下来：这给出 32 分册第 3 节那 46 个
     * 导出里，Metal 实际会去取哪些。 */
    if (symbol && (strncmp(symbol, "AIRNT", 5) == 0
                || strncmp(symbol, "MTLCompiler", 11) == 0)) {
        ensure_outdir();
        note("[airdump] dlsym \"%s\" -> %p\n", symbol, r);
    }
    return r;
}

/* 记录 dlopen：plugin 的真实磁盘路径就在这里。
 * `91` 第 5.1 节的 R-001（libAppleParavirtCompilerPlugin.dylib 的路径）
 * 由这一条关闭。 */
static void *(*real_dlopen)(const char *, int) = NULL;

void *my_dlopen(const char *path, int mode) {
    if (!real_dlopen)
        real_dlopen = (void *(*)(const char *, int))dlsym(RTLD_NEXT, "dlopen");
    void *h = real_dlopen ? real_dlopen(path, mode) : NULL;
    if (path && (strstr(path, "CompilerPlugin") || strstr(path, "MTLCompiler")
              || strstr(path, "Paravirt"))) {
        ensure_outdir();
        note("[airdump] dlopen(\"%s\", %#x) -> %p\n", path, mode, h);
    }
    return h;
}

__attribute__((used)) static struct {
    const void *replacement;
    const void *replacee;
} interposers[] __attribute__((section("__DATA,__interpose"))) = {
    { (const void *)(uintptr_t)&my_dlsym,  (const void *)(uintptr_t)&dlsym  },
    { (const void *)(uintptr_t)&my_dlopen, (const void *)(uintptr_t)&dlopen },
};
