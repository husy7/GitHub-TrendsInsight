# 面试问答

> 配套项目：[GitHub Trends Insight](../README.md)。回答都对应仓库里的真实实现，可直接对照代码与测试。

**Q1. GitHub 没有 Trending API，你怎么做?**
直接抓 `https://github.com/trending` 的 HTML，用固定选择器解析（`article.Box-row` 卡片、
`h2.h3 a` 取 `repo_full_name`、`span[itemprop="programmingLanguage"]` 取 `language`、
`a[href$="/stargazers"]` 取 `stars`）。语言筛选走路径（`/trending/python?since=daily`），周期走
`?since=daily|weekly|monthly`。选择器一旦改版解析就会返回空列表，采集任务直接失败并报警，
不会写入半截数据；解析器用真实页面结构的 fixture 做回归测试。

**Q2. Rate Limit 怎么处理?**
所有 API 请求带 Token（5,000 req/hr），重试策略为
`delay = min(BASE_DELAY * 2**attempt, MAX_DELAY)` 加 0~1 秒抖动，默认
`MAX_RETRIES=5` / `BASE_DELAY=2` / `MAX_DELAY=60`；403/429 优先读 `Retry-After`（超过 `MAX_DELAY`
会截断并记日志），5xx 按退避重试，404 直接写入 `failed_repos` 且不重试。每次响应都记录
`X-RateLimit-Remaining` / `X-RateLimit-Reset`，剩余量 <= 1 时告警；同一采集任务内同一仓库只请求一次详情。
Token 缺失时直接报错退出，不做任何绕过。

**Q3. Star Velocity 怎么算?**
两种口径，单位都是 "Star/天"：

- **周期增量口径（优先）**：`star_velocity_{n}d = stars_in_period / n`，其中 `stars_in_period`
  取自 weekly 榜单的 "stars this week" / monthly 榜单的 "stars this month"，首次采集当天即可算出。
- **历史快照口径（回退）**：`(stars(T) - stars(T - n 天)) / n`，只有恰好存在 `T - n` 天快照时才计算。

两种情况缺失都整行省略，写 `NULL` 而不是 0。排名变化另算
`rank_momentum = 前一 snapshot_date 的 rank - 当日 rank`（正数=上升），无前一日数据同样省略。
产物按窗口命名：`language_share_<period>.csv`、`rank_momentum_<period>_<language>.csv`、
`star_velocity_top7d.csv` / `star_velocity_top30d.csv`。

**Q4. 你的分析和直接看 Trending 页面有什么区别?**
页面只给"此刻"的名次与当前窗口增量；本项目把每天的榜单落库成时间序列，于是能算跨天的
Star Velocity（谁在加速）、Rank Momentum（谁在往上冲）、语言占比变化（哪种语言在变热），
以及"存量榜第 3 但增速榜第 1"这类页面看不出的错位。数据还能被重复查询、画图、导出 CSV 与 Markdown 报告。

**Q5. 为什么这个项目适合数据采集 / 数据分析实习?**
它覆盖完整链路：反直觉的数据源（没有 API 只能解析 HTML）→ 带重试和限流的采集 → 幂等存储与唯一约束 →
纯函数指标体系（有边界测试）→ 报告 CSV / Markdown 与仪表板 → CI 每日调度 + 数据回写仓库。
工程约束也是真实工作里的约束：覆盖率门槛 70%、`ruff` / `mypy --strict` 全绿、术语表统一命名、
原始响应压缩归档并保留 90 天。

**Q6. 为什么用 uv 而不是 pip / poetry?**
uv 一个工具同时管 Python 版本、虚拟环境、锁文件与工具运行（`uv python install`、`uv sync`、`uv run`、`uvx`）；
`uv.lock` 保证本地与 CI 完全一致（`uv sync --frozen`），`uv run` 消除"忘记激活虚拟环境"类问题，
解析与安装速度明显快于 pip，也不需要维护 poetry 的 `pyproject` + lock 双份心智负担。

**Q7. 定时任务跑在临时 runner 上，数据怎么留住?**
GitHub 托管 runner 每次都是全新机器，所以工作流在分析完成后把 `data/trends.db` 与 `data/processed/`
以 `chore: daily snapshot <date> [skip ci]` 提交回仓库（`permissions: contents: write`）；
Streamlit Cloud 监听仓库并随 push 自动重建，时间序列与站点因此持续更新，`data/raw/` 体积大不入库。

## 简历描述（量化模板）

> 独立开发 GitHub 趋势分析项目：每日采集 Trending 榜单（无官方 API，自研 HTML 解析器），
> 累计采集 **__ 天 / __ 个仓库 / __ 种语言**，计算 Star Velocity 与 Rank Momentum 指标，
> 识别出 **__ 个高速增长仓库**，用 Streamlit 交付可交互仪表板（访问量 **__**），
> 采集幂等 + Rate Limit 退避使任务成功率保持 **__%**。

> 数字必须来自真实采集结果：把 `uv run python scripts/analyze.py --days 30` 输出的
> `data/processed/repo_metrics.csv` 行数、`language` 去重数与 `failed_repos` 比例填进去即可。
