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
- 阶段 2（上游运行时和 Docker 镜像）：进行中；Qoder bootstrap 与 Compose 健康检查已完成，镜像尚未构建。
- 阶段 3（统一 router）：进行中；核心路由和 mock 协议验证已完成，仍需补测试文件和真实容器验证。
- 阶段 4（签到与凭证安全）：进行中；多账号执行和原子导出已完成，仍需做 mock HTTP 验证。
- Docker engine 尚未完成本项目镜像构建和端到端启动验证。
- 尚未写入真实账号、token、`.env` 或签到配置。

### 下一步

1. 启动 Docker engine 后构建 Qoder、codebuddy、router 镜像并验证健康检查和账号卷。
2. 为 router 和签到增加可重复的 mock 单元测试，覆盖流式、上游错误和多账号失败。
3. 修订 Docker 部署故障排查、备份说明和最终 GitHub 发布清单。

### 验证记录

- `python -m compileall -q router checkin docker/qoder-entrypoint.py`：通过。
- `python -m unittest discover -s router/tests -p 'test_*.py' -v`：3 项通过。
- `python -m unittest discover -s checkin/tests -p 'test_*.py' -v`：1 项通过。
- `docker compose config --quiet`（注入临时测试环境变量）：通过。
- `docker version`：失败，Docker Desktop Linux engine 未运行，因此镜像构建和容器启动暂未验证。

### 注意事项

- 不把真实 token、`.env`、`checkin/config.json` 或运行数据写入 Git。
- 不把 workbuddy-manager 直接指向 codebuddy2api，除非先完成协议适配或补齐其 Go 上游。
- 发布前必须更新 README/NOTICE，使源码快照、许可证和 Docker 使用方式与实际目录一致。
