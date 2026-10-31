# upstream metal2vulkan 可建性 — macos-26-intel

- ref: 219f01365dc4c8eb346816c405b5b17403793764
- rustc: rustc 1.98.0 (88d9e12ae 2026-08-18)

| 步骤 | 结果 |
|---|---|
| cargo metadata | success |
| cargo check（3 个已发布 crate） | success |
| cargo check --workspace --all-features | success |
| cargo check --target x86_64-apple-darwin | success |
