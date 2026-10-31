# upstream metal2vulkan 可建性 — ubuntu-latest

- ref: 219f01365dc4c8eb346816c405b5b17403793764
- rustc: rustc 1.99.1 (58cf8f9c3 2026-10-13)

| 步骤 | 结果 |
|---|---|
| cargo metadata | success |
| cargo check（3 个已发布 crate） | success |
| cargo check --workspace --all-features | success |
| cargo check --target x86_64-apple-darwin | skipped |
