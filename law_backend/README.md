# 法律工作台后端

完整说明见项目根目录 [README](../README.md)。

由 `crewai create flow law_backend` 初始化，已改为 MySQL 队列驱动的法律分析 Flow。不要沿用示例任务或设置 OPENAI_API_KEY；DeepSeek / TokenHub 在工作台设置页配置。

```bash
uv sync --python 3.12 --locked
uv run alembic upgrade head
uv run uvicorn law_backend.api:app --host 127.0.0.1 --port 8891
# 另一终端
uv run law-worker
```

根目录 `.env` 为唯一环境配置来源，本目录无需额外 `.env`。
