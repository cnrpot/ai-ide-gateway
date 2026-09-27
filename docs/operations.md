# 部署与运维

## 启动、升级和停止

```bash
cp .env.example .env
# 编辑 .env，至少设置 GATEWAY_API_KEYS、PANEL_ADMIN_KEY、QODER_BACKEND_KEY、
# QODER_ADMIN_PASSWORD、CODEBUDDY_ADMIN_KEY 和 CODEBUDDY_BACKEND_KEY
docker compose up -d --build
docker compose ps
```

默认只发布 `8080` 一个宿主机端口。`http://localhost:8080/` 是统一工作台，直接管理 Qoder、WorkBuddy/CodeBuddy 和三家签到，不依赖原生控制台页面。

升级源码后重新构建并滚动重启：

```bash
docker compose build --pull
docker compose up -d
docker compose ps
```

不要在升级时使用 `docker compose down -v`，这会删除账号池和 Qoder 配置卷。普通停止使用 `docker compose stop`；确认不再需要容器后才使用 `docker compose down`。

## 数据卷

Compose 默认创建以下卷：

- `ai-ide-gateway_qoder-data`：Qoder SQLite、账号和配置；
- `ai-ide-gateway_codebuddy-auth`：CodeBuddy 登录凭据；
- `ai-ide-gateway_codebuddy-management`：CodeBuddy 管理数据；
- `./checkin`：共享签到配置和日志（`config.json`、`checkin.log` 被 Git 忽略）。

实际卷名以 `docker volume ls` 为准；如果使用了自定义 Compose project name，前缀会随之变化。

## 备份与恢复

先停止会写入数据的服务，再把卷打包到宿主机的 `backups` 目录：

```bash
mkdir -p backups
docker compose stop router qoder codebuddy checkin
docker run --rm -v ai-ide-gateway_qoder-data:/source -v "$PWD/backups:/backup" alpine \
  tar czf /backup/qoder-data.tgz -C /source .
docker run --rm -v ai-ide-gateway_codebuddy-auth:/source -v "$PWD/backups:/backup" alpine \
  tar czf /backup/codebuddy-auth.tgz -C /source .
docker run --rm -v ai-ide-gateway_codebuddy-management:/source -v "$PWD/backups:/backup" alpine \
  tar czf /backup/codebuddy-management.tgz -C /source .
tar czf backups/checkin-config.tgz -C checkin config.json checkin.log 2>/dev/null || true
docker compose start qoder codebuddy checkin
```

恢复前停止服务，并确认目标卷就是当前 Compose 项目创建的卷：

```bash
docker compose stop router qoder codebuddy checkin
docker run --rm -v ai-ide-gateway_qoder-data:/target -v "$PWD/backups:/backup" alpine \
  sh -c 'rm -rf /target/* && tar xzf /backup/qoder-data.tgz -C /target'
docker run --rm -v ai-ide-gateway_codebuddy-auth:/target -v "$PWD/backups:/backup" alpine \
  sh -c 'rm -rf /target/* && tar xzf /backup/codebuddy-auth.tgz -C /target'
docker run --rm -v ai-ide-gateway_codebuddy-management:/target -v "$PWD/backups:/backup" alpine \
  sh -c 'rm -rf /target/* && tar xzf /backup/codebuddy-management.tgz -C /target'
tar xzf backups/checkin-config.tgz -C checkin 2>/dev/null || true
docker compose up -d
```

备份文件包含登录凭据，应按密钥材料保存，不能提交 Git 或上传到公共位置。`checkin/config.json` 是单独的明文 token 文件，使用宿主机安全备份，不要把它放进源码目录的提交中。

## 故障排查

```bash
docker compose ps
docker compose logs --tail=100 qoder codebuddy router
curl http://localhost:8080/health
curl http://localhost:8080/health/ready
```

`/health` 只表示 router 进程存活；`/health/ready` 会探测两个后端。若后端健康但对话返回“无可用账号”，请登录统一工作台，在 Qoder 或 WorkBuddy 标签页导入/授权账号。真实对话请求不能在没有上游账号时完成。

## 统一工作台

工作台需要 `PANEL_ADMIN_KEY`，登录后由 router 使用 `QODER_ADMIN_PASSWORD` 和 `CODEBUDDY_ADMIN_KEY` 调用内部管理 API。浏览器只接触工作台会话，不接触后端管理密钥。工作台提供账号、密钥、调度、配额、签到配置和立即签到操作；所有敏感 token 只写入后端存储并在列表中脱敏。

`/qoder/`、`/codebuddy/` 路径代理只为兼容旧排障流程保留。日常操作请使用根路径的统一工作台；生产 HTTPS 反代后设置 `PANEL_COOKIE_SECURE=1`。

启用 Trae 签到：在 Windows 上运行 `checkin/extract_tokens_windows.py` 生成 `checkin/config.json`，然后执行：

```bash
docker compose --profile checkin up -d --build checkin
docker compose logs -f checkin
```

token 过期后重新打开客户端刷新登录态，再重新导出配置；签到容器不会自动刷新 Windows 客户端 token。
