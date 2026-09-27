# WorkBuddy / Qoder / Trae 统一网关实施计划

## 目标

把 `项目.txt` 中的三个上游项目整理成一个可维护、可复现、支持 Docker Compose 的项目：

- Qoder 对话能力由 `QoderGateway` 提供；
- WorkBuddy / 腾讯 CodeBuddy 对话能力由 `codebuddy2api` 提供；
- Trae 在当前范围内只接入自动签到，不假设存在 Trae 对话网关；
- 通过新的统一 router 暴露 OpenAI Chat、OpenAI Responses、Anthropic Messages 和模型列表入口；
- 保留 `workbuddy-manager` 作为协议、签到和管理 UI 的参考来源，只有在补齐它依赖的 `workbuddy2api` Go 上游后才作为可选管理面板运行；
- 最终形成可在本地构建、健康检查、运行和发布到 GitHub 的仓库。

## 已确定的边界和决策

1. **对话后端**：采用 QoderGateway + codebuddy2api 两个后端，不把三个仓库强行合并成一个 Python 应用。
2. **Trae**：只实现签到。三个上游仓库没有 Trae 对话 API，另行逆向 Trae 对话协议会扩大范围，暂不纳入。
3. **workbuddy-manager**：不直接接到 codebuddy2api 上。它依赖外部 `Sliverkiss/workbuddy2api` Go 服务，账号格式、健康检查和配置接口均不兼容；先作为参考源码和可选后续集成点。
4. **上游引入方式**：当前网络环境无法稳定执行 `git clone`，三个目录先固定为官方 ZIP 对应的源码快照，并在 `NOTICE` 和来源清单中记录 URL、提交 SHA、许可证。恢复 submodule 作为后续可选维护工作，不能让当前构建依赖网络上的 submodule。
5. **凭证**：容器不读取 Windows 客户端的本地加密凭证。Qoder/WorkBuddy 通过各自控制台纳管账号；Trae 由 Windows helper 只读导出 token 到被挂载的 `checkin/config.json`。不自动刷新 refresh token。
6. **安全默认值**：router 默认要求网关 API key；健康检查可以公开，模型和对话接口必须鉴权。后端管理端口不发布到宿主机，敏感卷不提交 Git。
7. **统一工作台入口**：router 只发布宿主机 `8080`；用户在一个页面直接管理四个模块。`/qoder/` 和 `/codebuddy/admin/` 仅作为兼容排障路径保留。

## 阶段和状态

### 阶段 0：源码获取与来源固定 — `complete`

- [x] 读取 `项目.txt` 的三个仓库地址。
- [x] 由于 `github.com:443` 的 clone 连接失败，改用 GitHub 官方 ZIP 归档落地源码。
- [x] 固定源码目录：`providers/qoder`、`providers/workbuddy-manager`、`providers/codebuddy`。
- [x] 记录当前上游提交：
  - QoderGateway `d00376cdb4e74cc0f1714d5a22e94815426c5731`
  - workbuddy-manager `d8297b55b1512e56dc9037d87829d5b069b01a24`
  - codebuddy2api `1366be7dab45797a744a45106eb9dce2cb20984c`
- [x] 确认快照没有 `.git` 历史，父仓库目前只有未提交文件，尚无 `.gitmodules`。

### 阶段 1：需求、协议和风险审查 — `complete`

- [x] 确认 QoderGateway 提供 `/v1/chat/completions`、账号池、token 刷新和 WebUI，默认端口 5050。
- [x] 确认 codebuddy2api 提供 `/v1/chat/completions`、`/v1/responses`、`/v1/messages`、`/v1/models`、`/health`，默认端口 8787，并内置账号池和每日签到。
- [x] 确认 workbuddy-manager 依赖外部 `workbuddy2api` Go 服务，不能仅靠当前三个目录独立运行。
- [x] 确认 Trae 只在签到 Markdown 中出现，没有可直接复用的对话后端。
- [x] 发现旧草稿与实际状态不一致：README 声称 submodule，但当前是源码快照；router 尚未提供 `/v1/responses`；Qoder 不会自动把 `QODER_BACKEND_KEY` 当作 SQLite `allowed_keys`。
- [x] 将事实、取舍、风险和外部来源写入 `findings.md`。

### 阶段 2：上游运行时和 Docker 镜像 — `complete`

- [x] 设计并验证 QoderGateway 的 Linux 镜像：构建前端，跳过仅 Windows 的 `pypiwin32`/`drissionpage` 强依赖，持久化 `/data/.qoder`。
- [x] 为 Qoder 增加可重复的 API 鉴权初始化：容器入口把 `QODER_BACKEND_KEY` 写入 SQLite `allowed_keys`，默认启用鉴权。
- [x] 验证 codebuddy2api 独立 admin 镜像、`ADMIN_KEY` 长度约束、auth/management 卷和 `/health` 探活。
- [x] 为 router、Qoder、codebuddy、checkin 补充 Compose 健康检查、依赖顺序、卷、重启策略和内网端口暴露。
- [x] 明确控制台端口、数据卷和日志的备份/迁移方式。

### 阶段 3：统一 router — `complete`

- [x] 保留并重构统一 API-key 校验；缺少 key 时按安全默认失败，只有 `ALLOW_ANONYMOUS=1` 才允许匿名。
- [x] 实现模型路由：显式 `qoder/<model>`、`codebuddy/<model>` 优先，其次 `MODEL_ROUTES`，再按模型前缀和默认 provider 兜底。
- [x] 支持并完成 mock 协议验证：`/v1/chat/completions`、`/v1/responses`、`/v1/messages`、`/v1/models`；Anthropic/Responses 固定走 codebuddy。
- [x] 处理非流式状态码、上游错误体、超时和流式 SSE；错误信息不包含后端密钥。
- [x] 对外响应只保留必要的 content-type、cache-control、retry-after 和 request id，避免暴露内部服务地址。
- [x] 为路由、鉴权、流式转发和错误映射补充小而有意义的单元测试。

### 阶段 4：签到与凭证安全 — `complete`

- [x] 保留 Trae 独立签到，完善状态查询、领取、响应校验、超时和多账号继续执行逻辑。
- [x] Qoder/WorkBuddy 的独立签到默认关闭，避免与两个后端内置签到重复；保留显式开关供只跑签到场景使用。
- [x] 修复多账号 `all(...)` 的首个失败短路，输出每个账号结果和总体失败状态。
- [x] 防止 token 导出失败覆盖现有配置；成功写入采用临时文件 + 原子替换，并限制日志脱敏。
- [x] 检查 `extract_tokens_windows.py` 的 Windows 依赖、明文配置提醒和只读行为，明确 token 过期后的人工刷新步骤。
- [x] 为调度器增加时区、重复触发、退出码和日志轮转/卷持久化说明。

### 阶段 5：验证和运维文档 — `complete`

- [x] 运行 Python 编译、router/checkin 单元测试和必要的上游回归测试。
- [x] 在 Docker engine 可用后执行 `docker compose config`、四个镜像构建、启动、健康检查和停止/重启验证。
- [x] 用 mock 或本地测试后端验证模型路由、非流式/流式请求、`/v1/responses` 和 `/v1/messages`。
- [x] 用脱敏测试配置验证 Trae 多账号签到、已签到、失败重试和日志结果；真实账号验证留给部署机器。
- [x] 更新 README、`.env.example`、故障排查、升级/备份说明，修正 submodule 文字并增加源码快照清单。
- [x] 完善 `NOTICE`，列出三个 MIT 上游、第三方依赖和未打包的 workbuddy2api 依赖。

### 阶段 6：父仓库提交与 GitHub 发布 — `complete`

- [x] 清理密钥、token、构建产物和本地数据，检查 Git diff 和敏感信息。
- [x] 初始化/整理父仓库提交，提交可复现的源码快照、router、签到、Docker 和文档。
- [x] 配置 GitHub remote；本次创建公开仓库 `cnrpot/ai-ide-gateway` 并推送 `main`。
- [x] push 后用 GitHub 干净发布归档验证源码测试、镜像构建和最小启动流程（当前网络的 Git fetch 会卡住，因此使用官方 tarball 复核）。

### 阶段 7：单端口兼容层 — `complete`

- [x] 增加面板登录、HMAC 会话 Cookie、登出、状态探测和控制台链接 API。
- [x] 让 Qoder、WorkBuddy/CodeBuddy 控制台通过 router 的 `/qoder/`、`/codebuddy/` 路径访问，并重写 HTML、JavaScript、CSS、Location 和 Cookie 路径。
- [x] 移除 Qoder `5050`、CodeBuddy `8787` 的宿主机端口映射，只保留 router `8080`。
- [x] 增加路径代理和本机 Cookie 行为的单元测试。
- [x] 使用 Docker Engine 29.6.1 重建并验证面板、两条路径入口、CodeBuddy 管理会话和端口收敛。

### 阶段 8：单页统一工作台 — `complete`

- [x] 审查 Qoder `/ui/*`、CodeBuddy `/admin/api/*` 和签到脚本的可复用管理接口。
- [x] 新增 router 管理适配层和统一 `/panel/api/overview` 聚合接口，屏蔽 Provider 管理密钥。
- [x] 在同一页面加入 Qoder 账号/PAT/Token/配额、WorkBuddy 授权/账号池/API Key、三家签到配置和立即执行操作。
- [x] 共享宿主机 `checkin` 配置目录，支持不启动独立 profile 时从工作台手动执行签到。
- [x] 重建 Docker 并完成真实容器内的统一 overview、Qoder/CodeBuddy 管理 API 和签到配置操作验证。
- [x] 创建本地提交；推送在当前网络可用时执行。

## 验收标准

- `docker compose config` 通过，router、Qoder、codebuddy 可以启动，checkin profile 可选启动。
- 统一工作台可登录并在一个页面显示和操作 Qoder、WorkBuddy/CodeBuddy、Trae 签到及网关状态。
- `docker compose ps` 只显示 router 的宿主机端口映射，后端端口不直接暴露。
- `/health` 可用；`/v1/models` 需要网关 key 且返回带 provider 前缀的模型；模型路由和三个协议入口均有自动化验证。
- 流式和非流式请求均能正确透传或返回可诊断错误，后端密钥不会出现在响应和日志中。
- Trae 签到在无真实凭证时安全跳过，在测试凭证下能报告每个账号结果；Qoder/WorkBuddy 不会因重复签到影响网关。
- README、NOTICE、`.env.example` 与实际目录和部署方式一致；Git 历史不包含 token、`.env` 或签到配置。

## 失败记录

| 操作 | 结果 | 后续处理 |
|---|---|---|
| 直接 `git clone` 三个 GitHub 仓库 | `github.com:443` 连接失败 | 使用 GitHub 官方 ZIP 归档，固定源码快照和提交 SHA |
| 把 `workbuddy-manager` 直接当作 WorkBuddy 后端 | 依赖缺失的外部 Go `workbuddy2api`，接口/账号格式不兼容 | 仅作参考；若后续需要 UI，再单独补齐适配层或 Go 上游 |
| 以 `QODER_BACKEND_KEY` 直接鉴权 Qoder | Qoder 实际读取 SQLite `auth_required`/`allowed_keys` | 阶段 2 增加初始化或明确首次配置步骤 |
| 仅聚合原生控制台链接 | 仍需用户在多个页面管理账号和签到 | 新增统一管理适配层和单页操作界面，原生路径只保留兼容用途 |

## 发布记录

- GitHub：<https://github.com/cnrpot/ai-ide-gateway>
- 默认分支：`main`
- 发布提交：`6c8002f`
- 部署前仍需在目标机器导入真实 Qoder/CodeBuddy 账号，并按 `.env.example` 设置密钥；没有上游账号时网关只能完成健康检查和模型探测。
