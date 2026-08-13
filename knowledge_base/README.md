# 知识库（Obsidian Vault）

用 Obsidian「打开文件夹作为仓库」打开本目录即可管理知识库（markdown + YAML frontmatter）。

- **新增/修改/删除** .md 文档后，调用 `POST /api/v1/kb/reindex` 重建索引（需 `X-API-Key`）
- frontmatter 支持 `title` / `category` / `status`；`status: draft` 的文档**不会进入检索**（待审核）
- `backfill/` 目录存放「人工兜底 → 知识回填」自动生成的条目，草稿确认发布后进入检索
- 相关接口：`GET /api/v1/kb/docs` 查看全部文档
