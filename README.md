# ai-ide-gateway

把 **Qoder**、**WorkBuddy / 腾讯 CodeBuddy** 两家 AI 编程工具聚合成**一个 OpenAI 兼容网关**，
并为 **Qoder / Trae / WorkBuddy** 提供**每日自动签到**。一条 `docker compose` 命令部署。

> 说明：本项目聚合的三个上游里，QoderGateway 对应 Qoder，另外两个（workbuddy-manager、
> codebuddy2api）其实**都是腾讯 CodeBuddy/WorkBuddy**。**没有 Trae 的对话网关**，
> 所以 **Trae 目前只做签到**，对话聚合覆盖 Qoder + WorkBuddy。

## 架构

```
   统一工作台 :8080 ──► router / panel ──┬─ Qoder 管理 API       :5050
                                         ├─ WorkBuddy 管理 API   :8787
                                         └─ Trae/Qoder/WB 签到配置与执行器

   OpenAI 客户端 ──Bearer <网关key>──► router :8080  ──┬─ model=qoder/*     ─► qoder     :5050 ─► api2-v2.qoder.sh
   /v1/chat/completions /v1/responses /v1/messages  └─ model=codebuddy/* ─► codebuddy :8787 ─► copilot.tencent.com

   checkin （每日定时，默认只跑 Trae；Qoder/WorkBuddy 的签到已由各自后端自动完成）
```

- **router**（本项目新写）：统一入口，统一 API-key 鉴权，按模型名把请求分发到后端，SSE 流式透传。
- **qoder**：[bzym2/QoderGateway](https://github.com/bzym2/QoderGateway) 的固定源码快照 + 我们补的 Dockerfile。
- **codebuddy**：[ShouZhuo0413/codebuddy2api](https://github.com/ShouZhuo0413/codebuddy2api) 的固定源码快照和 admin 控制台，自带账号池 + 每日签到。
- **checkin**（本项目新写）：由社区签到脚本改造，token 走配置文件，容器可跑。

上游 [ithtelab/workbuddy-manager](https://github.com/ithtelab/workbuddy-manager) 仅作协议参考，未打包。详见 `NOTICE`。

## 快速开始

```bash
# 1. 克隆本项目（上游源码快照已经包含在 providers/ 下）
git clone <your-repo-url> ai-ide-gateway
cd ai-ide-gateway

# 2. 配置
cp .env.example .env
#   至少设置：GATEWAY_API_KEYS、PANEL_ADMIN_KEY、QODER_BACKEND_KEY、QODER_ADMIN_PASSWORD、CODEBUDDY_ADMIN_KEY、CODEBUDDY_BACKEND_KEY

# 3. 启动（router + qoder + codebuddy）
docker compose up -d --build

# 4. 健康检查
curl http://localhost:8080/health
```

## 统一工作台

启动后访问 `http://localhost:8080/`，输入 `PANEL_ADMIN_KEY`。这是实际的单页管理工作台，不会把你跳转到三个原生控制台。页面直接提供：

- Qoder PAT 添加、批量导入、账号启停/切换、Token 刷新和配额查询；
- WorkBuddy / CodeBuddy 授权、账号池调度、单账号/批量签到、额度刷新和客户端 API Key 管理；
- Trae、Qoder、WorkBuddy 签到账号的脱敏列表、添加/删除和立即执行；
- 网关健康状态、模型路由、签到日志和四个模块的统一概览。

Qoder 和 CodeBuddy 端口只在 Compose 内网开放，页面由 router 使用各自后端的管理 API 完成操作。旧的 `/qoder/`、`/codebuddy/` 原生路径仍保留作兼容排障入口，但日常管理不需要使用它们。

## 账号纳管

Docker 里读不到 Windows 客户端的加密登录态。启动后直接在统一工作台的 Qoder、WorkBuddy 标签页添加账号即可；页面只返回账号名、UID、状态、额度和脱敏提示，不回显 token。Qoder 容器启动时会把 `QODER_BACKEND_KEY` 写入 SQLite `allowed_keys`，router 才能安全转发。

## 模型命名与路由

router 按下面顺序决定把请求发给哪个后端：

1. **显式前缀**（推荐，无歧义）：`qoder/<模型>`、`codebuddy/<模型>`，如 `codebuddy/glm-5.2`、`qoder/lite`。
2. `.env` 的 `MODEL_ROUTES`（JSON 裸名映射）。
3. 内置规则：`lite`→qoder；`glm-*/deepseek-*/kimi-*/hy*/minimax*/auto`→codebuddy。
4. 兜底 `DEFAULT_PROVIDER`。

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_API_KEYS" -H "Content-Type: application/json" \
  -d '{"model":"codebuddy/auto","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

`GET /v1/models` 会返回带 `qoder/`、`codebuddy/` 前缀的聚合模型列表。

## 签到

统一工作台的“统一签到”标签页可以直接维护三家的 token 并立即执行签到。Qoder / WorkBuddy 后端仍保留各自的自动签到能力；独立 scheduler 适合无人值守的定时执行。

```bash
# 1. 在你的 Windows 机器上导出本地 token（只读客户端登录态，不改任何文件）
pip install pycryptodome
python checkin/extract_tokens_windows.py        # 生成 checkin/config.json
#   或手动 cp checkin/config.example.json checkin/config.json 后填 token

# 2. 可选：启用定时签到容器
docker compose --profile checkin up -d --build
docker compose logs -f checkin
```

也可以不启动 profile，直接在统一工作台点击某一家“立即签到”；router 会使用共享的 `checkin/config.json` 执行一次。

- 签到只读 token、不自动刷新 refresh token（刷新会导致客户端登出）。token 临期需开一次客户端刷新。
- 签到时刻、开关见 `.env` 的 `CHECKIN_*`。手动跑一次：`python -m checkin.scheduler --once`。

## 对外端点（router）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（无需鉴权） |
| GET | `/health/ready` | 后端依赖就绪检查（后端不可达时返回 503） |
| GET | `/v1/models` | 聚合模型列表（需要网关 key） |
| POST | `/v1/chat/completions` | OpenAI 兼容对话（流式/非流式） |
| POST | `/v1/responses` | OpenAI Responses（固定走 codebuddy 后端） |
| POST | `/v1/messages` | Anthropic 兼容（固定走 codebuddy 后端） |

部署升级、数据卷备份恢复和故障排查见 [`docs/operations.md`](docs/operations.md)。

## 安全提示

- `router` 是唯一对外端口。默认要求 `GATEWAY_API_KEYS`；即使为空也会拒绝 `/v1` 请求，只有显式设置 `ALLOW_ANONYMOUS=1` 才允许匿名。
- Qoder、CodeBuddy 管理端口不发布到宿主机；统一工作台是唯一管理入口。对外部署请加 HTTPS 反向代理并配置 `PANEL_COOKIE_SECURE=1`。
- `checkin/config.json` 含明文 token，已在 `.gitignore` 中，切勿提交或外传。

## 目录结构

```
router/       统一入口（新写）
providers/    三个固定源码快照（qoder、codebuddy、workbuddy-manager）
docker/       两个后端的 Dockerfile（build context = 仓库根）
checkin/      签到脚本 + 调度 + Windows token 导出 helper
docs/         补充文档
```

## 致谢与许可

本项目 MIT。聚合的上游项目版权归各自作者，均为 MIT，详见 `NOTICE`。仅供个人学习研究。
