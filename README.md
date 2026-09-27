# ai-ide-gateway

把 **Qoder**、**WorkBuddy / 腾讯 CodeBuddy** 两家 AI 编程工具聚合成**一个 OpenAI 兼容网关**，
并为 **Qoder / Trae / WorkBuddy** 提供**每日自动签到**。一条 `docker compose` 命令部署。

> 说明：本项目聚合的三个上游里，QoderGateway 对应 Qoder，另外两个（workbuddy-manager、
> codebuddy2api）其实**都是腾讯 CodeBuddy/WorkBuddy**。**没有 Trae 的对话网关**，
> 所以 **Trae 目前只做签到**，对话聚合覆盖 Qoder + WorkBuddy。

## 架构

```
   OpenAI 客户端 ──Bearer <网关key>──► router :8080  ──┬─ model=qoder/*     ─► qoder     :5050 ─► api2-v2.qoder.sh
   /v1/chat/completions /v1/models /v1/messages       └─ model=codebuddy/* ─► codebuddy :8787 ─► copilot.tencent.com

   checkin （每日定时，默认只跑 Trae；Qoder/WorkBuddy 的签到已由各自后端自动完成）
```

- **router**（本项目新写）：统一入口，统一 API-key 鉴权，按模型名把请求分发到后端，SSE 流式透传。
- **qoder**：[bzym2/QoderGateway](https://github.com/bzym2/QoderGateway)（submodule）+ 我们补的 Dockerfile。
- **codebuddy**：[ShouZhuo0413/codebuddy2api](https://github.com/ShouZhuo0413/codebuddy2api)（submodule）的 admin 控制台，自带账号池 + 每日签到。
- **checkin**（本项目新写）：由社区签到脚本改造，token 走配置文件，容器可跑。

上游 [ithtelab/workbuddy-manager](https://github.com/ithtelab/workbuddy-manager) 仅作协议参考，未打包。详见 `NOTICE`。

## 快速开始

```bash
# 1. 递归克隆（含两个 submodule）
git clone --recursive <your-repo-url> ai-ide-gateway
cd ai-ide-gateway
# 若忘了 --recursive：git submodule update --init --recursive

# 2. 配置
cp .env.example .env
#   至少设置：GATEWAY_API_KEYS、CODEBUDDY_ADMIN_KEY、CODEBUDDY_BACKEND_KEY

# 3. 启动（router + qoder + codebuddy）
docker compose up -d --build

# 4. 健康检查
curl http://localhost:8080/health
```

## 账号纳管

Docker 里读不到你 Windows 本地客户端的加密登录态，所以账号通过各自控制台在线纳管：

- **Qoder**：浏览器打开 `http://127.0.0.1:5050` → 用 `QODER_ADMIN_PASSWORD` 登录 →
  用 PAT 导入账号（或在 `.env` 里预填 `QODER_PAT` 首次自动导入）。Qoder 的签到由它自动完成。
- **WorkBuddy/CodeBuddy**：浏览器打开 `http://127.0.0.1:8787` → 用 `CODEBUDDY_ADMIN_KEY` 登录 →
  扫码授权 CN 账号。它自带账号池轮询 + 每日签到（默认 09:00）。

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

Qoder / WorkBuddy 的签到已由各自后端自动完成，**独立签到服务默认只跑 Trae**。

```bash
# 1. 在你的 Windows 机器上导出本地 token（只读客户端登录态，不改任何文件）
pip install pycryptodome
python checkin/extract_tokens_windows.py        # 生成 checkin/config.json
#   或手动 cp checkin/config.example.json checkin/config.json 后填 token

# 2. 启用签到容器
docker compose --profile checkin up -d --build
docker compose logs -f checkin
```

- 签到只读 token、不自动刷新 refresh token（刷新会导致客户端登出）。token 临期需开一次客户端刷新。
- 签到时刻、开关见 `.env` 的 `CHECKIN_*`。手动跑一次：`python -m checkin.scheduler --once`。

## 对外端点（router）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（无需鉴权） |
| GET | `/v1/models` | 聚合模型列表 |
| POST | `/v1/chat/completions` | OpenAI 兼容对话（流式/非流式） |
| POST | `/v1/messages` | Anthropic 兼容（固定走 codebuddy 后端） |

## 安全提示

- `router` 是唯一对外端口。**务必在 `.env` 配 `GATEWAY_API_KEYS`**，否则网关无鉴权，切勿裸暴露公网。
- 两个控制台默认只绑定 `127.0.0.1`，仅本机可访问；对外请加 HTTPS 反向代理。
- `checkin/config.json` 含明文 token，已在 `.gitignore` 中，切勿提交或外传。

## 目录结构

```
router/       统一入口（新写）
providers/    qoder、codebuddy 两个 submodule
docker/       两个后端的 Dockerfile（build context = 仓库根）
checkin/      签到脚本 + 调度 + Windows token 导出 helper
docs/         补充文档
```

## 致谢与许可

本项目 MIT。聚合的上游项目版权归各自作者，均为 MIT，详见 `NOTICE`。仅供个人学习研究。

