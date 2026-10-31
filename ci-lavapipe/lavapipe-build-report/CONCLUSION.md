# Lavapipe on x86_64 macOS — 构建结论

- runner: 26.6.1 (25G76), x86_64
- mesa ref: mesa-25.3.2
- loader ref: v1.4.321
- llvm: 20.1.8

| 步骤 | 结果 |
|---|---|
| Vulkan-Loader 构建 | success |
| Mesa meson setup | failure |
| Mesa ninja 构建 | failure |
| loader dlopen 自检 | success |
