# 上线配置

日常同步由 GitHub Actions 在线完成。本地电脑、VS Code 和本地 Python 环境都不需要保持运行。

## 1. 创建只读 Token

1. 打开 GitHub 的 **Settings → Developer settings → Personal access tokens → Fine-grained tokens**。
2. 选择 **Generate new token**。
3. Token 名称可填写 `MyPR Record`。
4. 设置合理的过期时间，例如一年，并为续期设置提醒。
5. Resource owner 选择自己的账号。
6. 保持最小仓库访问范围，不授予写权限。Fine-grained token 默认具有对 GitHub 公共仓库的只读访问；PR 搜索端点不要求额外权限。
7. 生成并立即复制 Token；离开页面后无法再次查看完整值。

如果只记录公开仓库，不要授予私有仓库读取权限。Token 应像密码一样保管。

## 2. 添加 Actions Secret

1. 打开本仓库的 **Settings → Secrets and variables → Actions**。
2. 选择 **New repository secret**。
3. Name 填写 `PR_READ_TOKEN`。
4. Secret 填写上一步生成的 Token。

Token 只会提供给“Synchronize and render”步骤，不会写入数据、日志或 Git 提交。

## 3. 允许 Action 提交结果

打开 **Settings → Actions → General → Workflow permissions**，选择 **Read and write permissions** 并保存。

工作流自身还显式限制为 `contents: write`，只用于更新当前仓库的展示文档和 PR 数据。如果默认分支启用了禁止直接推送的保护规则，需要允许 GitHub Actions 推送，或者为这个个人记录仓库调整对应规则。

## 4. 首次运行

1. 将项目文件推送到默认分支。
2. 打开仓库的 **Actions** 页面。
3. 选择 **Sync pull requests**。
4. 点击 **Run workflow**。
5. 运行完成后，确认产生一条 `chore: sync pull request record` 提交。

此后工作流会在每天北京时间 03:17 左右执行。GitHub Actions 在繁忙时可能延迟，定时任务不保证精确到分钟。

## 同步模式

- **定时运行**固定使用增量模式，只搜索最近新建的 PR，并刷新本地仍为 Open 的 PR。
- **手动运行**可以在 `sync_mode` 中选择 `full` 或 `incremental`，默认使用 `full`。
- **增量模式**不会重新查询或覆盖本地已有的 Merged/Closed 记录；Open PR 变为 Merged/Closed 后会保存最终状态。
- **全量模式**会重新查询全部 PR，可用于首次建立数据、校准历史记录或恢复以前被排除的 PR。
- 如果本地尚无 PR 数据，即使选择增量模式也会自动执行一次全量同步。

增量搜索会向前保留一天的重叠窗口，并按 GitHub Node ID 去重，避免定时任务延迟或日期边界造成遗漏。

## 排除仓库

编辑根目录配置中的 `github.excluded_repositories`：

```yaml
github:
  excluded_repositories:
    - "WhatGhost/MyPR_record"
    - "WhatGhost/whatghost_Notebooks"
    - "example-org/*"
    - "*/scratch-*"
```

规则特点：

- 使用完整的 `owner/repository` 名称。
- 匹配时忽略大小写。
- 支持 `*`、`?` 和字符范围等 shell 风格通配符。
- 被排除仓库的 PR 不进入明细、年度统计或总统计。
- 新增规则后，下一次同步会移除以前已经记录的匹配 PR。
- 删除规则后，手动运行一次 `full` 同步，才能重新查询并加入对应的旧 PR。

## 添加个人备注

个人备注使用 `owner/repository#PR编号` 作为键：

```yaml
"microsoft/vscode#12345":
  category: "文档"
  note: "修复 Windows 环境下的路径解析问题"
  highlight: true
```

字段都是可选的：

- `category`：个人分类，显示在备注前。
- `note`：个人总结。
- `highlight`：设为 `true` 时在明细中加星标。

修改备注后，可以等待下一次定时同步，也可以在 Actions 页面手动运行。

## 本地可选操作

本地操作不是日常同步的必要条件。需要预览备注或排除规则时，可以安装项目后执行：

```text
python -m pr_record render
```

本地执行同步还需要把 `PR_READ_TOKEN` 安全地放入当前终端环境；不要把 Token 写入配置文件：

```text
python -m pr_record sync          # 增量同步
python -m pr_record sync --full   # 全量同步
```

## 常见问题

### `PR_READ_TOKEN is required`

Secret 尚未创建、名称不完全一致，或者 Token 已过期。

### HTTP 401 或 GraphQL 认证错误

Token 无效、已撤销或已过期。重新生成 Token 并更新 Secret。

### `git push` 被拒绝

检查 Workflow permissions 和默认分支保护规则。

### 定时工作流停止运行

GitHub 会在公共仓库连续 60 天没有仓库活动时自动禁用定时工作流。进入 Actions 页面重新启用，然后手动运行一次即可。手动 `workflow_dispatch` 入口始终保留在工作流中。

### 某个旧 PR 没有再次出现在 GitHub 搜索中

增量同步会保留没有明确被排除的历史记录，避免仓库删除、转私有或搜索暂时不完整导致数据丢失。需要重新发现本地不存在的旧 PR 时，在 Actions 页面手动运行一次 `full` 同步。
