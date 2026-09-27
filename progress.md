# 工作进度

## 2026-09-27

### 已完成

- 读取并重新审查了用户给出的三个仓库地址和自动签到 Markdown。
- 确认三个上游源码已经落地到 `providers/qoder`、`providers/workbuddy-manager`、`providers/codebuddy`。
- 核对了上游固定 SHA、许可证、服务端口、协议入口、账号管理和签到能力。
- 核对父项目现有 router、compose、Dockerfile、签到脚本、README、`.env.example` 和 Git 状态。
- 发现父项目已初始化 Git 但尚无提交、remote 或 `.gitmodules`；三个 provider 都是源码快照。
- 创建了新的 `task_plan.md`、`findings.md`、`progress.md`，把旧计划中“submodule”和接口范围的过时描述改成当前事实。
- 在 `ai-ide-gateway` 初始化的 Git 仓库中创建了首个基线提交，提交了源码快照、规划文件和原始 Docker/路由草稿。
- 新增 Qoder 容器入口脚本，把 `QODER_BACKEND_KEY` 幂等写入 SQLite `allowed_keys`，并默认阻止后端匿名访问。
- router 增加 fail-closed 鉴权、`/health/ready`、`/v1/responses`、上游状态码/超时处理和流式 SSE 透传。
- Compose 增加四类服务的健康检查、Qoder/CodeBuddy 健康依赖和超时配置；README/NOTICE 改为描述源码快照而非 submodule。
- 签到脚本改为遍历全部账号并汇总结果；Windows token 导出改为失败不覆盖、成功原子替换。
- 新增 `router/tests/test_router.py` 和 `checkin/tests/test_common.py`，验证鉴权、模型路由、Responses/Messages、SSE 透传和多账号失败不短路。

### 当前状态

- 阶段 0（源码获取与来源固定）：完成。
- 阶段 1（需求、协议和风险审查）：完成。
- 阶段 2（上游运行时和 Docker 镜像）：完成；四个镜像均已构建，Qoder bootstrap、三项服务健康检查、签到容器启动和备份/迁移说明已完成。
- 阶段 3（统一 router）：完成；核心路由、mock 协议和真实容器健康/模型聚合验证已完成，真实对话需在部署机导入上游账号后验证。
- 阶段 4（签到与凭证安全）：完成；多账号执行、原子导出、Trae 调度容器启动和脱敏 mock HTTP 回归已完成。
- Docker engine 已恢复；router、Qoder、codebuddy、checkin 镜像均完成构建，前三个服务已完成端到端启动和健康检查。
- 尚未写入真实账号、token、`.env` 或签到配置。

### 下一步

项目已完成首版发布；后续工作是按需导入真实账号、验证真实模型调用并维护上游源码快照。

### 验证记录

- `python -m compileall -q router checkin docker/qoder-entrypoint.py`：通过。
- `python -m unittest discover -s router/tests -p 'test_*.py' -v`：3 项通过。
- `python -m unittest discover -s checkin/tests -p 'test_*.py' -v`：1 项通过。
- `docker compose config --quiet`（注入临时测试环境变量）：通过。
- Docker Engine 29.6.1：已恢复。
- 四个镜像构建：通过（`router`、`qoder`、`codebuddy`、`checkin`）。
- `docker compose up -d`：通过；`qoder`、`codebuddy`、`router` 均 healthy。
- `GET /health`、`GET /health/ready`：通过；两个 provider 均报告可达。
- 无网关 key 的 `/v1/models`：401；带网关 key 的 `/v1/models`：返回 `qoder/` 和 `codebuddy/` 聚合模型。
- Qoder 容器 SQLite bootstrap：`auth_required=True`，测试后端 key 已写入 `allowed_keys`。
- 无上游账号时，Qoder/CodeBuddy 对话请求按预期返回无可用账号错误；不是镜像启动故障。
- `docker compose --profile checkin up -d --build checkin`：通过；日志显示默认仅启用 Trae 调度器。
- GitHub 公开仓库已创建并推送：<https://github.com/cnrpot/ai-ide-gateway>；官方 tarball 干净归档已通过编译、单元测试、四镜像重建、临时端口启动、健康检查和模型聚合验证。

### 注意事项

- 不把真实 token、`.env`、`checkin/config.json` 或运行数据写入 Git。
- 不把 workbuddy-manager 直接指向 codebuddy2api，除非先完成协议适配或补齐其 Go 上游。
- 发布前必须更新 README/NOTICE，使源码快照、许可证和 Docker 使用方式与实际目录一致。
