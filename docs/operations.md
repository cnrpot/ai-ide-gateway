# 部署与运维

## 启动、升级和停止

```bash
cp .env.example .env
# 编辑 .env，至少设置 GATEWAY_API_KEYS、QODER_BACKEND_KEY、
# CODEBUDDY_ADMIN_KEY 和 CODEBUDDY_BACKEND_KEY
docker compose up -d --build
docker compose ps
```

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
- `ai-ide-gateway_checkin-log`：签到日志。

实际卷名以 `docker volume ls` 为准；如果使用了自定义 Compose project name，前缀会随之变化。

## 备份与恢复

先停止会写入数据的服务，再把卷打包到宿主机的 `backups` 目录：

```bash
mkdir -p backups
docker compose stop qoder codebuddy checkin
docker run --rm -v ai-ide-gateway_qoder-data:/source -v "$PWD/backups:/backup" alpine \
  tar czf /backup/qoder-data.tgz -C /source .
docker run --rm -v ai-ide-gateway_codebuddy-auth:/source -v "$PWD/backups:/backup" alpine \
  tar czf /backup/codebuddy-auth.tgz -C /source .
docker run --rm -v ai-ide-gateway_codebuddy-management:/source -v "$PWD/backups:/backup" alpine \
  tar czf /backup/codebuddy-management.tgz -C /source .
docker compose start qoder codebuddy checkin
```

恢复前停止服务，并确认目标卷就是当前 Compose 项目创建的卷：

```bash
docker compose stop qoder codebuddy checkin
docker run --rm -v ai-ide-gateway_qoder-data:/target -v "$PWD/backups:/backup" alpine \
  sh -c 'rm -rf /target/* && tar xzf /backup/qoder-data.tgz -C /target'
docker run --rm -v ai-ide-gateway_codebuddy-auth:/target -v "$PWD/backups:/backup" alpine \
  sh -c 'rm -rf /target/* && tar xzf /backup/codebuddy-auth.tgz -C /target'
docker run --rm -v ai-ide-gateway_codebuddy-management:/target -v "$PWD/backups:/backup" alpine \
  sh -c 'rm -rf /target/* && tar xzf /backup/codebuddy-management.tgz -C /target'
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

`/health` 只表示 router 进程存活；`/health/ready` 会探测两个后端。若后端健康但对话返回“无可用账号”，请分别打开 `http://127.0.0.1:5050` 和 `http://127.0.0.1:8787` 导入或授权账号。真实对话请求不能在没有上游账号时完成。

启用 Trae 签到：在 Windows 上运行 `checkin/extract_tokens_windows.py` 生成 `checkin/config.json`，然后执行：

```bash
docker compose --profile checkin up -d --build checkin
docker compose logs -f checkin
```

token 过期后重新打开客户端刷新登录态，再重新导出配置；签到容器不会自动刷新 Windows 客户端 token。
