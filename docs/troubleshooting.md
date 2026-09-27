# 故障排查

## 构建

- **qoder 镜像构建失败（pip 安装报 pypiwin32/drissionpage）**
  上游 `pyproject.toml` 把这两个 Windows/浏览器依赖列成无平台标记的强依赖。本仓库的
  `docker/qoder.Dockerfile` 已改成「只装核心依赖 + `pip install --no-deps .`」绕开。若你自行改动
  构建方式，注意别用 `uv sync` / `pip install .`（会拉这两个包，Linux 上必失败）。

- **qoder 前端构建失败**
  前端只影响控制台 UI，不影响 `/v1/*` 与 `/ui/*` API。可先忽略，账号纳管仍可用 API 完成。

- **codebuddy 镜像**
  未使用上游 `deploy/admin/Dockerfile`（它依赖预构建基础镜像 `local/codebuddy2api:<sha>`），
  改用 `docker/codebuddy.Dockerfile` 独立构建。

## 运行

- **router 502 / 连不上后端**
  确认 `qoder`、`codebuddy` 容器已 healthy；router 用服务名 `http://qoder:5050`、
  `http://codebuddy:8787` 在 compose 内网访问。

- **codebuddy 请求 401**
  router 转发时带的 `CODEBUDDY_BACKEND_KEY` 必须等于 codebuddy 的 `CODEBUDDY2OPENAI_KEY`
  （compose 已用同一个 `.env` 值绑定）。

- **qoder 返回空 / TOKEN_INVALID**
  账号未导入或 token 过期。到 `127.0.0.1:5050` 控制台重新导入 PAT。

- **模型分发错**
  用显式前缀 `qoder/xxx` 或 `codebuddy/xxx` 最稳；或在 `.env` 的 `MODEL_ROUTES` 里补裸名映射。

## 签到

- **Trae 签到查询状态失败 / 过期**
  token 过期。重新运行 `checkin/extract_tokens_windows.py` 导出，或手动更新 `checkin/config.json`。
- **CryptUnprotectData failed（导出脚本）**
  DPAPI 主密钥只在当前 Windows 交互用户会话可用；请在你自己登录的桌面会话里运行导出脚本。
