# 研究与审查记录

## 来源与源码状态

`项目.txt` 当前列出：

- https://github.com/bzym2/QoderGateway
- https://github.com/ithtelab/workbuddy-manager
- https://github.com/ShouZhuo0413/codebuddy2api

当前工作树中的对应目录是 ZIP 源码快照，不含 `.git`：

| 目录 | 上游 | 当前固定 SHA | 许可证 | 用途 |
|---|---|---|---|---|
| `providers/qoder` | QoderGateway | `d00376cdb4e74cc0f1714d5a22e94815426c5731` | MIT | Qoder 对话后端、账号池、WebUI、签到 |
| `providers/workbuddy-manager` | workbuddy-manager | `d8297b55b1512e56dc9037d87829d5b069b01a24` | MIT | 管理 UI、协议/签到参考；当前不直接运行 |
| `providers/codebuddy` | codebuddy2api | `1366be7dab45797a744a45106eb9dce2cb20984c` | MIT | WorkBuddy/CodeBuddy 对话后端、admin、账号池、签到 |

直接 clone 曾因当前环境无法连接 `github.com:443` 失败，随后使用 GitHub 官方 ZIP 归档完成落地。由于快照没有 Git 元数据，发布前必须保留来源 URL、SHA 和下载日期，不能在 README 中继续声称它们是 submodule。

## 能力边界

### QoderGateway

- FastAPI/Python，默认 5050。
- 提供 `/v1/chat/completions`，有 Qoder WebUI、SQLite 账号池、token 刷新和自动 claim。
- `pyproject.toml` 将 `drissionpage`、`pypiwin32` 列为无平台标记依赖。Linux 镜像不能直接按完整依赖安装；浏览器注册机不是本项目容器运行的必需路径，应拆出核心运行依赖。
- API 鉴权由 SQLite 的 `auth_required` 和 `allowed_keys` 控制，源码没有 `QODER_BACKEND_KEY` 环境变量直通逻辑。router 转发 key 前必须先初始化 Qoder 的允许列表，或明确首次控制台配置步骤。

### codebuddy2api

- Python/FastAPI，admin server 默认 8787。
- 提供 `/v1/chat/completions`、`/v1/responses`、`/v1/messages`、`/v1/models`、`/health`。
- 账号后台、浏览器登录、token 刷新、账号池和每日签到均已包含在项目中。
- `ADMIN_KEY` 至少 20 字符；`CODEBUDDY2OPENAI_KEY` 是后端 API key；`CODEBUDDY_AUTH_DIR` 和 `MANAGEMENT_DATA_DIR` 需要持久化。
- 上游 admin Dockerfile 依赖预构建基础镜像，本项目现有自写 Dockerfile 需继续做构建和运行验证。

### workbuddy-manager

- 它是围绕 `Sliverkiss/workbuddy2api` Go 服务的管理面板，不是独立 WorkBuddy 对话后端。
- 大量代码依赖 `WB2API_BASE`、`WB2API_KEY`、`/healthz`、Go 服务配置和 `workbuddy*.json` 账号格式。
- codebuddy2api 使用 `.info` 登录凭据和不同的管理数据格式；把 `WB2API_BASE` 指向 codebuddy2api 不能保证兼容。
- 可抽取其签到、账号审计和 UI 设计作为后续参考；若要打包 UI，必须另行引入或适配缺失的 Go 上游。

### Trae 签到 Markdown

- `Qoder_CN、Trae_CN、WorkBuddy免费签到脚本.md` 提供三家的签到/凭证思路。
- Docker 无法直接读取 Windows 客户端加密登录态，因此当前方案由 Windows helper 只读导出 token，再挂载 `checkin/config.json`。
- Qoder 和 WorkBuddy 后端已有自动签到，独立脚本默认关闭；Trae 没有可复用的对话网关，只保留独立签到。
- token 是敏感数据；配置文件必须被 `.gitignore` 排除，日志只显示短尾脱敏值，导出失败不能覆盖已有配置。

## 当前草稿的具体问题

1. `README.md` 和目录说明把 `providers/qoder`、`providers/codebuddy` 写成 submodule，但实际无 `.gitmodules`、无子仓库历史。
2. router 当前只有 `/v1/chat/completions` 和 `/v1/messages`，缺少 codebuddy 已支持的 `/v1/responses`。
3. `GET /health` 只返回静态 `status=ok`，没有反映 Qoder/CodeBuddy 后端健康；需要区分存活和依赖健康，避免编排误判。
4. router 的 key 为空时会关闭鉴权。生产默认应 fail-closed，至少需要显式开发开关才能允许匿名。
5. router 的流式错误发生在响应开始后，只能追加 SSE 错误事件；需要记录上游状态并在可行时保留状态码/错误体。
6. 三个签到 `run()` 使用 `all(...)`，首个账号失败会短路，后续账号不会执行；应收集所有账号结果后返回总体状态。
7. Qoder 后端的 API key 需要写入 SQLite `allowed_keys`，不能只在 compose 中设置 `QODER_BACKEND_KEY`。

## 已实施的第一轮修正

- `router` 默认 fail-closed；`GATEWAY_API_KEYS` 为空时 `/v1/*` 仍返回 401，只有显式 `ALLOW_ANONYMOUS=1` 才允许匿名。
- 增加 `/v1/responses` 和 `/health/ready`；Responses/Messages 固定转发到 codebuddy，Chat 按模型前缀路由。
- Qoder 镜像增加 `qoder-entrypoint.py`，每次启动把 `QODER_BACKEND_KEY` 幂等写入 `allowed_keys`，并由 `QODER_REQUIRE_AUTH` 控制是否强制后端鉴权。
- Compose 增加 provider 健康检查和 router 的健康依赖；Docker engine 未运行，尚未完成实际镜像构建。
- 签到账号执行统一收集每个账号结果；Windows 导出在任一 provider 解密失败时不覆盖旧配置，成功时原子替换。
- mock 测试已覆盖鉴权、模型列表、provider key 隔离、三种协议和 SSE 透传。

## 设计取舍

- 采用“统一 router + 两个独立后端 + 可选签到容器”，比把两个成熟后端重写成一个应用更容易升级和回滚。
- 采用源码快照而非当前不可用的 submodule，先保证离线可构建；通过 `NOTICE`、来源清单和固定 SHA 保留可追溯性。
- 管理端口只绑定 `127.0.0.1`；对外访问由用户自行配置 HTTPS 反代，避免在 compose 中默认暴露账号管理界面。
- Trae token 从 Windows 导出脚本进入容器，是能力边界而不是自动刷新机制；临期后需要用户打开客户端重新导出。

## 待验证问题

- Qoder 初次启动如何以非交互方式可靠写入 `auth_required=true` 和 `allowed_keys`，以及控制台 API 是否适合做一次性 bootstrap。
- Qoder 前端构建、Linux 运行和账号 PAT 导入在当前 Docker engine 上是否成功。
- codebuddy2api 自写独立镜像是否遗漏 admin server 的运行时文件或静态资源。
- router 对 `/v1/responses` 的请求体、流式格式和 codebuddy 错误码是否需要协议适配，而不是简单转发。
- Docker engine 启动后四个服务的健康检查、数据卷权限和重启行为。
