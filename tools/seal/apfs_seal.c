/*
 * apfs_seal.c —— 对一个 APFS 卷做「封印」与「设 root snapshot」。
 *
 * 为什么要有这个东西
 * ------------------
 * `bless --create-snapshot` 在一块从零建出来的卷上被直接拒绝：
 *
 *     Can't use snapshot options on non ARV volume
 *     Snapshot manipulation failed            → 退出码 2
 *
 * 即 bless 要求目标卷**已经**是 ARV（Authenticated Root Volume），所以它封不了
 * 第一次印。详见 docs/spec/78-APFS-VOLUME-CONSTRUCTION.md 第 A.10.2c 节（V-034）。
 *
 * 而 Apple 自己怎么做的，已经从 UpdateBrainLibrary.x86_64.dylib 反编译出来了
 * （78 §A.10.2d）。去掉日志与 NSError 包装之后，它的两个方法各自只剩四行：
 *
 *     -[LPStaticAPFSVolume createSnapshot:error:]   RVA 0x145024
 *         fd = open(volume.mountPoint, O_RDONLY);
 *         fs_snapshot_create(fd, name, 0);
 *         close(fd);
 *
 *     -[LPStaticAPFSVolume rootToSnapshot:error:]   RVA 0x1463b5
 *         fd = open(volume.mountPoint, O_RDONLY);
 *         fs_snapshot_root(fd, name, 0);
 *         close(fd);
 *
 * 本文件就是这两段的直接等价物。三条值得记住的细节，都是从反编译读出来的：
 *   1. 打开的是**挂载点**，不是 /dev/diskNsM。所以卷必须先挂载。
 *   2. 两处的 flags 参数都是字面 0 —— 没有「封印模式」之类的隐藏标志。
 *   3. fs_snapshot_* 是 libSystem 的公开导入符号（dylib 的 __stubs 段里六个都在），
 *      不是需要手写 syscall() 的私有 SPI。
 *
 * 封印本身（SSV 的 Merkle root hash）由 APFS 内核在 fs_snapshot_create 的那一刻算，
 * 不签名、不联网（77 §D.1 已证）。我们**不需要** Apple 的签名：研发期
 * csr-active-config 的 bit 11（CSR_ALLOW_UNAUTHENTICATED_ROOT）正是为「启动一个
 * 未经认证的根」而存在的（70 §5.2、71 §6.7 的 0xFEF 已包含它）。
 *
 * 编译
 * ----
 *     cc -O2 -Wall -Wextra -o apfs_seal apfs_seal.c
 * 没有第三方依赖，只用 <sys/snapshot.h>。
 *
 * 用法
 * ----
 *     apfs_seal create <挂载点> <快照名>   # = createSnapshot:error:
 *     apfs_seal root   <挂载点> <快照名>   # = rootToSnapshot:error:
 *     apfs_seal revert <挂载点> <快照名>   # 回滚（排障用）
 *     apfs_seal delete <挂载点> <快照名>
 *     apfs_seal seal   <挂载点> <快照名>   # create + root，一步到位
 *
 * 快照清单用 `diskutil apfs listSnapshots <挂载点>` 读，本程序不实现 list ——
 * fs_snapshot_list 要自己组 attrlist 缓冲区，而我们并不需要它。
 *
 * 护栏
 * ----
 * 这个程序会改一个卷的 root snapshot，对 / 跑就是在动当前运行的系统。
 * 所以它**硬拒绝**几个路径，而且不提供绕过开关。更外层的护栏（确认目标不在
 * 运行器的根盘上）在调用方，见 78 §A.10.2 与 forensics workflow 里的 whole_of()。
 */

#include <errno.h>
#include <fcntl.h>
#include <limits.h>   /* PATH_MAX */
#include <stdint.h>   /* uint32_t */
#include <stdio.h>
#include <stdlib.h>   /* realpath */
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <sys/snapshot.h>

/*
 * fs_snapshot_root 在某些 SDK 的 <sys/snapshot.h> 里没有声明（它在 libSystem 里
 * 确实导出 —— UpdateBrainLibrary 就是正常链接它的）。补一个兼容原型：若头文件
 * 已经声明过同一个原型，重复声明是合法的；若没声明，这一行让链接找得到它。
 */
#ifndef SNAPSHOT_OP_ROOT
extern int fs_snapshot_root(int dirfd, const char *name, uint32_t flags);
#endif

/* 绝对不能动的路径。前缀匹配。 */
static const char *const kForbidden[] = {
    "/",
    "/System",
    "/System/Volumes/Data",
    "/System/Volumes/Preboot",
    "/System/Volumes/VM",
    "/System/Volumes/Update",
    "/Users",
    "/private",
    NULL,
};

static int refuse_if_forbidden(const char *path)
{
    char real[PATH_MAX];
    if (realpath(path, real) == NULL) {
        fprintf(stderr, "apfs_seal: realpath(%s): %s\n", path, strerror(errno));
        return -1;
    }
    for (int i = 0; kForbidden[i] != NULL; i++) {
        if (strcmp(real, kForbidden[i]) == 0) {
            fprintf(stderr,
                    "apfs_seal: 拒绝对 '%s'（realpath '%s'）操作 —— "
                    "它是当前运行系统的一部分。\n",
                    path, real);
            return -1;
        }
    }
    struct stat st;
    if (stat(real, &st) != 0) {
        fprintf(stderr, "apfs_seal: stat(%s): %s\n", real, strerror(errno));
        return -1;
    }
    if (!S_ISDIR(st.st_mode)) {
        fprintf(stderr, "apfs_seal: '%s' 不是目录。这里要的是卷的**挂载点**。\n", real);
        return -1;
    }
    return 0;
}

/* 打开挂载点。与 Apple 的两个方法一致：O_RDONLY，不加别的标志。 */
static int open_mountpoint(const char *path)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        fprintf(stderr, "apfs_seal: open(%s): %s\n", path, strerror(errno));
    return fd;
}

static int do_op(const char *op, const char *mnt, const char *name)
{
    int fd = open_mountpoint(mnt);
    if (fd < 0)
        return 1;

    int rc;
    if (strcmp(op, "create") == 0)
        rc = fs_snapshot_create(fd, name, 0);
    else if (strcmp(op, "root") == 0)
        rc = fs_snapshot_root(fd, name, 0);
    else if (strcmp(op, "revert") == 0)
        rc = fs_snapshot_revert(fd, name, 0);
    else if (strcmp(op, "delete") == 0)
        rc = fs_snapshot_delete(fd, name, 0);
    else {
        fprintf(stderr, "apfs_seal: 不认识的操作 '%s'\n", op);
        close(fd);
        return 2;
    }

    int saved = errno;
    close(fd);

    if (rc != 0) {
        fprintf(stderr, "apfs_seal: fs_snapshot_%s(\"%s\", \"%s\", 0) 失败："
                        "rc=%d errno=%d (%s)\n",
                op, mnt, name, rc, saved, strerror(saved));
        /* 把 errno 也反映进退出码，便于 shell 分支（截到 1..120）*/
        return saved > 0 && saved < 120 ? saved : 1;
    }
    printf("apfs_seal: fs_snapshot_%s(\"%s\", \"%s\", 0) 成功\n", op, mnt, name);
    return 0;
}

static void usage(void)
{
    fputs(
        "用法: apfs_seal <create|root|revert|delete|seal> <挂载点> <快照名>\n"
        "\n"
        "  create  = -[LPStaticAPFSVolume createSnapshot:error:]  （造快照，内核算 seal）\n"
        "  root    = -[LPStaticAPFSVolume rootToSnapshot:error:]  （设为 root snapshot）\n"
        "  seal    = 先 create 再 root\n"
        "  revert / delete  排障用\n"
        "\n"
        "快照清单用 `diskutil apfs listSnapshots <挂载点>` 读。\n"
        "依据：docs/spec/78-APFS-VOLUME-CONSTRUCTION.md 第 A.10.2d 节。\n",
        stderr);
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        usage();
        return 2;
    }
    const char *op = argv[1], *mnt = argv[2], *name = argv[3];

    if (name[0] == '\0') {
        fprintf(stderr, "apfs_seal: 快照名不能为空"
                        "（Apple 的实现对空名返回 EINVAL/22）。\n");
        return 2;
    }
    if (refuse_if_forbidden(mnt) != 0)
        return 2;

    if (strcmp(op, "seal") == 0) {
        int rc = do_op("create", mnt, name);
        if (rc != 0)
            return rc;
        return do_op("root", mnt, name);
    }
    return do_op(op, mnt, name);
}
