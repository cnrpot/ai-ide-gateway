"""把请求里的 model 解析成 (provider, upstream_model)。

解析优先级：
1. 显式前缀  provider/model  -> 剥掉前缀
2. MODEL_ROUTES 里的裸名映射
3. 内置命名规则（前缀匹配）
4. DEFAULT_PROVIDER
"""
from __future__ import annotations

from .config import settings

KNOWN = ("qoder", "codebuddy")

# 内置「模型名前缀 -> provider」规则
_PREFIX_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("qoder", ("lite", "qoder")),
    ("codebuddy", ("glm-", "deepseek-", "kimi-", "hy", "minimax", "auto")),
)


def resolve(model: str) -> tuple[str, str]:
    """返回 (provider, upstream_model)。"""
    model = (model or "").strip()
    if not model:
        return settings.default_provider, "auto"

    # 1. 显式前缀 provider/model
    if "/" in model:
        head, rest = model.split("/", 1)
        if head in KNOWN and rest:
            return head, rest

    # 2. 配置映射表
    prov = settings.model_routes.get(model)
    if prov in KNOWN:
        return prov, model

    # 3. 内置命名规则
    low = model.lower()
    for provider, prefixes in _PREFIX_RULES:
        if any(low.startswith(p) for p in prefixes):
            return provider, model

    # 4. 兜底
    return settings.default_provider, model
