# airdump 产物的性质

这里的 `*.bin` 是 **Metal.framework 交给 compiler plugin 的输入**，
其中 `air-*.bin` 来自**本项目自己写的 shader**
（`tools/ci/shaders/*.metal`），不是 Apple 的内容。

`flatbuf-*.bin` 是 Metal.framework 生成的描述结构。它是 Apple 代码
的输出，但不是 Apple 的代码本体，体积在 KB 量级，且它的全部价值在于
结构而非内容。按 `.gitignore` 顶部的发布边界，**这些 blob 不进仓库**；
进仓库的是从它们推出的 schema 结论（写入 `docs/spec/32-COMPILER-PLUGIN.md`）。
