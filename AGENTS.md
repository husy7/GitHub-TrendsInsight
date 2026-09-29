## 0. 术语表（命名唯一来源）

所有代码、文档、SQL、API 字段必须使用下表标识符。禁止同义词替换。

| 概念 | 唯一标识符 | 禁止写法 |
|---|---|---|
| 仓库全名 | `repo_full_name` | `repo`, `full_name`, `owner/repo` |
| 快照日期（UTC） | `snapshot_date` | `date`, `day` |
| 趋势周期 | `period` | `since`, `range` |
| 语言筛选值 | `language` | `lang` |
| Star 总数 | `stars` | `star_count`, `stargazers` |
| Fork 总数 | `forks` | `forks_count` |
| 7 日星标速度 | `star_velocity_7d` | `velocity_7d`, `sv7` |
| 30 日星标速度 | `star_velocity_30d` | `velocity_30d`, `sv30` |
| 排名动量 | `rank_momentum` | `momentum`, `rank_delta` |
| 语言占比 | `language_share` | `lang_share` |
| 周期内新增 Star | `stars_in_period` | `stars_today`, `stars_this_week`, `stars_this_month` |
| 环境变量（本地） | `GITHUB_TOKEN` | `GH_TOKEN`, `GH_PAT`（仅 Actions secret 使用） |
| Actions secret | `GH_PAT` | `GITHUB_TOKEN`（避免与内置混淆） |

规则：
- SQL 列名、pandas 列名、Python 参数名、仪表板筛选字段必须完全一致。
- 新增字段必须先在本表登记，再改代码。

---

## 1. 项目定位

项目名：`github-trends-insight`

目标：构建一个面向数据采集 / 数据分析实习求职的作品集项目。

核心能力：
1. 定时采集 GitHub Trending 与仓库详情数据。
2. 保存历史时间序列，支持趋势对比。
3. 计算 Star Velocity、Rank Momentum、语言分布等指标。
4. 用 Streamlit 提供可交互仪表板。
5. 用 GitHub Actions 每日自动采集。

成功标准：
- 能连续采集至少 7~30 天数据。
- 仪表板可公开访问，README 有截图和结论。
- 面试时能解释：为什么没有 Trending API、如何处理 Rate Limit、Star Velocity 如何计算、与直接看 Trending 页面的区别。

非目标：
- 不做全量 GitHub 镜像。
- 不绕过 GitHub Rate Limit。
- 不采集用户隐私数据。
- 不为了“显得高级”强行引入 TensorFlow、Spark、Kafka。
- 预测模型是可选加分项，不是 MVP 必需项。
- MVP 阶段禁止实现 GraphQL；GraphQL 只在 v0.2 之后作为独立 PR 引入。

---

## 2. 技术栈与包管理

运行环境：
- Python 3.11+（以 `.python-version` 为准）
- 包管理：**uv ≥ 0.5**（唯一允许的包管理与环境工具）
- 禁止使用 `pip`、`pip-tools`、`poetry`、`conda`、`virtualenv` 直接管理环境

核心依赖：
- 采集：`httpx` + `beautifulsoup4`
- 数据：`pandas`、SQLite（默认）
- 可视化：`streamlit` + `plotly`
- 配置：`pydantic-settings`
- 存储访问：`sqlalchemy`

开发依赖（dev group）：
- `pytest`、`pytest-cov`、`respx`
- `ruff`、`mypy`

调度：GitHub Actions

uv 约定：
- `pyproject.toml` 是唯一依赖声明源。
- `uv.lock` 必须提交到仓库。
- 运行任何 Python 命令一律通过 `uv run`，不手动激活虚拟环境。
- CI 中使用 `astral-sh/setup-uv@v5`，不安装系统 Python 包管理器。
- 禁止手动编辑 `uv.lock`。

检查 uv 版本：

```bash
uv --version   # 必须 >= 0.5.0
```

---

## 3. 推荐目录结构

```text
github-trends-insight/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .github/
│   └── workflows/
│       └── daily-collect.yml
├── scripts/
│   ├── collect.py
│   └── analyze.py
├── src/
│   └── trends/
│       ├── __init__.py
│       ├── config.py
│       ├── logging_setup.py
│       ├── collector/
│       │   ├── __init__.py
│       │   ├── trending_page.py
│       │   ├── github_api.py
│       │   └── rate_limit.py
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── db.py
│       │   └── models.py
│       ├── analysis/
│       │   ├── __init__.py
│       │   ├── metrics.py
│       │   └── reports.py
│       └── dashboard/
│           └── app.py
├── tests/
│   ├── fixtures/
│   │   ├── trending_daily.html
│   │   ├── trending_python.html
│   │   └── repo_api_response.json
│   ├── test_trending_parser.py
│   ├── test_github_api.py
│   └── test_metrics.py
└── data/
    ├── raw/
    └── processed/
```

---

## 4. 常用命令（uv）

```bash
# 安装 uv（若本机未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 初始化项目（只跑一次；uv init 会创建 .python-version）
uv init --python 3.11

# 添加运行依赖
uv add httpx beautifulsoup4 pandas streamlit plotly pydantic-settings sqlalchemy

# 添加开发依赖（uv 新版使用 dependency-groups）
uv add --dev pytest pytest-cov respx ruff mypy

# 同步环境
uv sync

# 严格同步（CI 必须使用）
uv sync --frozen

# 更新依赖并刷新 lock
uv lock --upgrade

# 运行脚本
uv run python scripts/collect.py --period daily --language ""
uv run python scripts/collect.py --period daily,weekly,monthly   # 三窗口一次采完
uv run python scripts/analyze.py --days 30
uv run streamlit run src/trends/dashboard/app.py

# 测试与检查
uv run pytest -q
uv run pytest --cov=trends --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src

# 一次性工具（不写入项目依赖）
uvx ruff check .
```

规则：
- 禁止出现 `python -m venv`、`source .venv/bin/activate`、`pip install`。
- 临时依赖用 `uv run --with <pkg>`，不污染 `pyproject.toml`。
- `uv init` 只跑一次；重复执行会覆盖，禁止在已有项目上重跑。

---

## 5. `pyproject.toml` 模板

`pyproject.toml` 必须与下列模板结构一致。dsh 生成或修改时必须保留全部字段。

```toml
[project]
name = "github-trends-insight"
version = "0.1.0"
description = "GitHub trending collector and analyzer for internship portfolio"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "pandas>=2.2",
    "streamlit>=1.36",
    "plotly>=5.22",
    "pydantic-settings>=2.4",
    "sqlalchemy>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-cov>=5.0",
    "respx>=0.21",
    "ruff>=0.6",
    "mypy>=1.11",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/trends"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]  # line-length 由 formatter 处理

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_ignores = true
warn_redundant_casts = true
disallow_untyped_defs = true
ignore_missing_imports = false
files = ["src"]
exclude = ["src/trends/dashboard/app.py"]  # Streamlit 入口暂不强制类型

[[tool.mypy.overrides]]
module = ["bs4.*", "streamlit.*", "plotly.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = [
    "network: 标记需要真实网络的测试（默认跳过）",
]

[tool.coverage.run]
source = ["src/trends"]
branch = true
omit = ["src/trends/dashboard/app.py"]

[tool.coverage.report]
fail_under = 70
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

规则：
- 新增依赖必须用 `uv add` / `uv add --dev`，禁止手工编辑 `dependencies`。
- 修改依赖后必须提交 `pyproject.toml` 与 `uv.lock`。
- `[tool.coverage.report] fail_under = 70` 是硬门槛，禁止改低。

---

## 6. 环境变量

`.env.example`：

```dotenv
GITHUB_TOKEN=
DATABASE_URL=sqlite:///data/trends.db
LOG_LEVEL=INFO
TRENDING_PERIOD=daily,weekly,monthly
TRENDING_LANGUAGE=
HTTP_TIMEOUT=15
MAX_RETRIES=5
BASE_DELAY=2
MAX_DELAY=60
```

规则：
- 禁止提交 `.env`。
- 禁止硬编码 Token。
- 本地使用 `GITHUB_TOKEN`；Actions 使用 `secrets.GH_PAT`（见 §13）。
- 测试中不得读取真实 `GITHUB_TOKEN`；`conftest.py` 必须设置 `monkeypatch.setenv("GITHUB_TOKEN", "test-token")` 或等价 mock。

---

## 7. 采集规则

### 7.1 数据源与请求头

所有 GitHub API 请求必须带：

```http
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Authorization: Bearer <GITHUB_TOKEN>
User-Agent: github-trends-insight
```

采集流程：
1. 抓取 `https://github.com/trending`，URL 参数：
   - `since=daily|weekly|monthly`（daily 卡片的增量是"今日"，weekly 是"近 7 天"，monthly 是"近 30 天"）
   - `spoken_language_code=`（可空）
   - 语言筛选通过路径：`https://github.com/trending/python?since=daily`
2. 对候选仓库调用 `GET /repos/{owner}/{repo}` 补详情。
3. MVP 阶段不做 GraphQL、不做 Search API 补充。

### 7.2 Trending HTML 解析规则

关键选择器（GitHub Trending 页面稳定结构）：

| 字段 | 选择器 | 说明 |
|---|---|---|
| 仓库卡片 | `article.Box-row` | 每个仓库一个 |
| 仓库全名 | `h2.h3 a` 的 `href`，去掉前导 `/` | `owner/repo` |
| 描述 | `p.col-9` | 可为空 |
| 语言 | `span[itemprop="programmingLanguage"]` | 可为空 |
| Star 总数 | 第一个 `a[href$="/stargazers"]` 的数字 | 需去逗号 |
| Fork 总数 | 第一个 `a[href$="/forks"]` 的数字 | 需去逗号 |
| 周期内新增 Star | `span.d-inline-block.float-sm-right` | 写入 `stars_in_period`，形如 `1,234 stars today` / `10,518 stars this week` / `19,771 stars this month` |

数字解析规则：
- 去掉 `,` 与空格。
- 支持 `1.2k` 后缀：k → ×1000，M → ×1_000_000。
- 无法解析时返回 `None`，不返回 0。

测试 fixture 必须覆盖：
- `tests/fixtures/trending_daily.html`：无语言筛选。
- `tests/fixtures/trending_python.html`：语言筛选，URL 带 `/python`。
- 每个 fixture 至少包含 3 个仓库，其中 1 个无 description、1 个无 language。

### 7.3 Rate Limit 硬约束

- 所有 API 请求携带 Token。
- 必须读取并记录：
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
  - `Retry-After`
- 重试策略（必须使用以下默认值，可通过 env 覆盖）：
  - `MAX_RETRIES=5`
  - `BASE_DELAY=2` 秒
  - `MAX_DELAY=60` 秒
  - 指数退避：`delay = min(BASE_DELAY * 2**attempt, MAX_DELAY)`
  - 加 0~1 秒随机抖动
- 遇 `403` / `429`：优先读 `Retry-After`，否则按上述退避。
- 遇 `5xx`：按退避重试。
- 遇 `404`：记录到 `failed_repos`，跳过，不重试。
- 同一采集任务内，同一仓库只请求一次详情。

### 7.4 幂等与保留策略

- 同一 `repo_full_name + snapshot_date + period + language` 不得重复插入。
- 历史快照只追加，不覆盖。
- 缺失字段写 `NULL`，禁止用 0 代替。
- 时区统一 UTC。
- `snapshot_date` 格式 `YYYY-MM-DD`；时间戳字段用 ISO8601 带 `Z`。
- `data/raw/` 保存 gzip 压缩的原始响应，保留最近 90 天，超出由采集脚本清理。

### 7.5 数据表（可执行 DDL）

```sql
CREATE TABLE IF NOT EXISTS trending_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL,
    period          TEXT    NOT NULL CHECK (period IN ('daily','weekly','monthly')),
    language        TEXT    NOT NULL DEFAULT '',
    rank            INTEGER NOT NULL,
    repo_full_name  TEXT    NOT NULL,
    stars           INTEGER,
    forks           INTEGER,
    stars_in_period INTEGER,
    description     TEXT,
    url             TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (repo_full_name, snapshot_date, period, language)
);

CREATE INDEX IF NOT EXISTS idx_trending_date_period
    ON trending_snapshots (snapshot_date, period, language);

CREATE TABLE IF NOT EXISTS repo_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_full_name  TEXT    NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    stars           INTEGER,
    forks           INTEGER,
    open_issues     INTEGER,
    language        TEXT,
    topics_json     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (repo_full_name, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_repo_snapshots_name_date
    ON repo_snapshots (repo_full_name, snapshot_date);

CREATE TABLE IF NOT EXISTS repo_metrics (
    repo_full_name     TEXT    NOT NULL,
    snapshot_date      TEXT    NOT NULL,
    star_velocity_7d   REAL,
    star_velocity_30d  REAL,
    rank_momentum      INTEGER,
    language_share     REAL,
    PRIMARY KEY (repo_full_name, snapshot_date)
);

CREATE TABLE IF NOT EXISTS failed_repos (
    repo_full_name  TEXT    NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    reason          TEXT    NOT NULL,
    status_code     INTEGER,
    PRIMARY KEY (repo_full_name, snapshot_date)
);
```

字段类型约定：
- 数值型缺失写 `NULL`，不用 0。
- `language` 统一小写；别名映射表放 `src/trends/config.py`。
- `topics_json` 为 JSON 数组字符串，元素按字典序排序。

---

## 8. 分析规则

### 8.1 指标函数签名（强制）

```python
# src/trends/analysis/metrics.py

def compute_star_velocity(
    snapshots: pd.DataFrame,
    window_days: int,
) -> pd.DataFrame:
    """
    Input columns:  repo_full_name, snapshot_date, stars
    Output columns: repo_full_name, snapshot_date, star_velocity_{window_days}d
    Missing window: row omitted (do not fill 0).
    """

def compute_rank_momentum(
    trending: pd.DataFrame,
    period: str,
    language: str,
) -> pd.DataFrame:
    """
    Input columns:  repo_full_name, snapshot_date, rank, period, language
    Output columns: repo_full_name, snapshot_date, rank_momentum
    previous_rank 取同 period + 同 language 下前一 snapshot_date 的 rank。
    无前一日数据：row omitted。
    """

def compute_language_share(
    trending: pd.DataFrame,
    period: str,
) -> pd.DataFrame:
    """
    Input columns:  language, snapshot_date, period
    Output columns: snapshot_date, language, language_share
    language_share = 当日该语言仓库数 / 当日全部趋势仓库数。
    """

def compute_period_star_velocity(
    trending: pd.DataFrame,
    period: str,
    window_days: int,
) -> pd.DataFrame:
    """
    Input columns:  repo_full_name, snapshot_date, stars_in_period, period
    Output columns: repo_full_name, snapshot_date, star_velocity_{window_days}d
    star_velocity = stars_in_period / window_days。
    周期增量口径 (weekly=近 7 天, monthly=近 30 天), 首次采集当天即可算出,
    不依赖历史快照。缺失 stars_in_period 的行省略。
    """
```

规则：
- 输入输出列名必须与上表一致。
- 数据不足时整行省略，不写 `NA`、不写 0。
- 函数必须无副作用、无 IO。
- 新增指标必须同步：本文件、`metrics.py`、测试、仪表板、README。
- `build_metrics_frame` 的 7d/30d 速度优先用周期增量口径（weekly/monthly），
  缺失时才回退到 `compute_star_velocity` 的历史快照差分。

### 8.2 输出位置

- `data/processed/` 下 CSV（`daily_language_share.csv` 等）。
- `data/processed/trending_report_<period>.md`：人类可读的 Markdown 报告，包含概览、
  Star Velocity Top N、Rank Momentum、语言占比、仓库明细（`description` + `url` 链接 + topics）。
- 或写入 SQLite `repo_metrics` 表。
- 仪表板只读 processed / `repo_metrics`，禁止直接打 GitHub API。

---

## 9. 仪表板规则

入口：`src/trends/dashboard/app.py`（单文件单页，MVP 阶段不拆包）。

必须包含：
1. 概览卡片：总 Star、今日新增、覆盖语言数、趋势仓库数。
2. 语言趋势折线图（按 `snapshot_date`）。
3. Star Velocity Top 10 横向柱状图。
4. 筛选器：
   - `language`（下拉，含“全部”）
   - `period`（daily / weekly / monthly）
   - 时间范围（最近 7 / 30 / 90 天）
5. 仓库详情：点击查看 stars / forks / open_issues / topics。
6. 导出报告：下载 `analyze.py` 生成的 `trending_report_<period>.md` 与同目录 CSV，
   并在页面内预览 Markdown（只读本地 processed 文件，不触发采集）。

要求：
- 使用 `st.cache_data` 缓存读取。
- 页面加载不得触发 GitHub API 请求。
- 移动端可用。
- 截图必须更新到 README。

---

## 10. 测试规则

- 解析器测试使用 `tests/fixtures/` 中 HTML，不打真实网络。
- API 测试使用 `respx` mock，禁止真实请求。
- 指标测试使用固定输入与固定输出。
- Bug 修复必须先写失败测试。
- 新功能必须补测试。
- 覆盖率门槛：`fail_under = 70`（见 `pyproject.toml`）。
- 禁止在测试中依赖真实 Token、真实网络、真实数据库。
- 所有测试通过 `uv run pytest` 执行。
- 标记为 `network` 的测试默认跳过；CI 中不运行。

`tests/fixtures/` 必须包含：
- `trending_daily.html`：无语言筛选。
- `trending_python.html`：语言筛选。
- `repo_api_response.json`：单仓库 API 响应样例。

---

## 11. 代码风格与日志

- `uv run ruff format` + `uv run ruff check` + `uv run mypy` 全绿。
- 纯函数优先；副作用集中在 `collector/` 与 `storage/`。
- 日志统一：`src/trends/logging_setup.py` 暴露 `setup_logging(level: str) -> None`。
  - 每个脚本入口（`scripts/collect.py`、`scripts/analyze.py`）调用一次。
  - 库代码使用 `logging.getLogger(__name__)`。
- 不要裸 `except`。
- 公共 API 写英文 docstring；业务解释可写中文注释。
- 使用 `pathlib`，不用 `os.path`。
- 数据模型用 `pydantic` 或 `dataclass`。
- 禁止引入未列入 `pyproject.toml` 的依赖。

---

## 12. Git / PR 规则

提交信息使用 Conventional Commits：

```text
feat: add trending page parser
fix: handle rate limit reset
test: add star velocity tests
docs: update AGENTS.md
chore: migrate to uv
```

禁止提交：`.env`、Token、`.venv/`、`__pycache__/`、`data/raw/` 大文件、隐私数据。

必须提交：`pyproject.toml`、`uv.lock`、`.python-version`。

PR 描述必须包含：变更内容、测试方式、UI 截图（如涉及）、是否影响 Rate Limit 或数据结构、`uv.lock` 变化说明。

---

## 13. GitHub Actions 与 uv

Secret 约定：
- Actions 中使用 `secrets.GH_PAT`（个人 Token，5,000 req/hr）。
- README 必须说明如何创建并配置 `GH_PAT`。
- 内置 `secrets.GITHUB_TOKEN` 不用于 API 采集（限额过低）。

`daily-collect.yml`：

```yaml
name: daily-collect

on:
  schedule:
    - cron: "30 0 * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: daily-collect
  cancel-in-progress: false

jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - name: Validate required secret
        env:
          GH_PAT: ${{ secrets.GH_PAT }}
        run: |
          if [ -z "$GH_PAT" ]; then
            echo "::error title=Missing GH_PAT secret::在 Settings → Secrets and variables → Actions → Secrets 添加名称精确为 GH_PAT 的 token"
            exit 1
          fi
          echo "GH_PAT 已注入 (length=${#GH_PAT})"

      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          version: "0.5.x"

      - name: Set up Python
        run: uv python install

      - name: Sync dependencies
        run: uv sync --frozen

      - name: Quality gate
        run: |
          uv run ruff check .
          uv run ruff format --check .
          uv run mypy src
          uv run pytest -q

      - name: Run collector
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
        run: uv run python scripts/collect.py --period daily,weekly,monthly

      - name: Run analysis
        run: uv run python scripts/analyze.py --days 30

      - name: Commit snapshots back to the repository
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -f data/trends.db data/processed
          if git diff --cached --quiet; then
            echo "no snapshot changes to commit"
          else
            git commit -m "chore: daily snapshot $(date -u +%F) [skip ci]"
            git push
          fi

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: processed-data
          path: data/processed/
```

规则：
- 禁止 `pip install -r requirements.txt`。
- 必须 `uv sync --frozen`。
- 采集脚本读取的 env 名是 `GITHUB_TOKEN`，Actions 中通过 `GITHUB_TOKEN: ${{ secrets.GH_PAT }}` 映射。
- Runner 是临时的，工作流**必须**把 `data/trends.db` 与 `data/processed/` 回写仓库
  （`permissions: contents: write` + `chore: daily snapshot ... [skip ci]` 提交后再 `git push`），
  否则跨天时间序列与 `rank_momentum` 会在第二天丢失，Streamlit Cloud 也读不到数据。
- `data/raw/` 不入库（体积大，只保留本地/runner 上的 90 天归档）。
- `GH_PAT` 必须是仓库级 **Secrets**（不是 Variables、不是 Environment），名称精确为 `GH_PAT`；
  工作流第一步 `Validate required secret` 会在缺失时直接失败并给出提示。

---

## 14. Agent 工作流

### 14.1 推荐生成顺序（严格按序）

1. `pyproject.toml`、`.python-version`、`.env.example`
2. `src/trends/config.py`
3. `src/trends/logging_setup.py`
4. `src/trends/storage/models.py`
5. `src/trends/storage/db.py`
6. `src/trends/collector/rate_limit.py`
7. `src/trends/collector/trending_page.py`
8. `src/trends/collector/github_api.py`
9. `src/trends/analysis/metrics.py`
10. `src/trends/analysis/reports.py`
11. `scripts/collect.py`
12. `scripts/analyze.py`
13. `src/trends/dashboard/app.py`
14. `tests/fixtures/*` + `tests/test_*.py`
15. `.github/workflows/daily-collect.yml`
16. `README.md`

禁止跳步；上一步未通过 `uv run pytest -q` 不得开始下一步。

### 14.2 每次修改前

1. 阅读 `README.md`、`AGENTS.md`、相关测试。
2. 确认修改属于采集、存储、分析、仪表板、调度还是依赖变更。
3. 检查是否影响 Rate Limit、数据幂等、历史快照、术语表。
4. 做最小变更，补测试。
5. 运行：

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

6. 新增依赖：`uv add` / `uv add --dev`，提交 `pyproject.toml` 与 `uv.lock`。
7. 新增 Python 版本要求：更新 `.python-version` 与 `requires-python`。
8. 接口或指标变更：更新本文件、README。
9. 不覆盖历史数据；迁移使用新表或新列。
10. 遇 Token 缺失或 Rate Limit 异常：停止并报告，不绕过。

---

## 15. 完成定义

新采集源完成：
- 有 Rate Limit 处理（§7.3 参数）。
- 有 fixture 测试（§10）。
- 有幂等写入（§7.4、§7.5）。
- README 更新。

新指标完成：
- 有纯函数实现，签名匹配 §8.1。
- 有单元测试。
- 仪表板展示。
- README 解释业务含义。

新依赖完成：
- 通过 `uv add` 添加。
- `uv.lock` 更新并提交。
- CI `uv sync --frozen` 通过。

新页面完成：
- 有筛选交互。
- 不直接请求 GitHub API。
- 更新截图。

---

## 16. 禁止事项

- 禁止伪造数据。
- 禁止硬编码 Token。
- 禁止在测试中打真实网络。
- 禁止删除历史快照。
- 禁止用多账号绕过 Rate Limit。
- 禁止为了炫技引入无关重型框架。
- 禁止只写 Notebook 不交付可运行系统。
- 禁止 `pip install` / `python -m venv` / `requirements.txt`。
- 禁止手动编辑 `uv.lock`。
- 禁止在 CI 中跳过 `--frozen`。
- 禁止使用术语表之外的同义标识符。
- 禁止在 MVP 阶段实现 GraphQL 或 Search API。

---

## 17. README 骨架（必须按此结构）

README 按 GitHub 通用规范组织，必须包含以下内容，顺序固定：

1. **标题 + 徽章 + 一句话介绍**：CI 状态、Python 版本、uv、License 徽章；一句话说明项目做什么、面向什么岗位。
2. **关键信息表 + 仪表板截图**：数据源 / 采集窗口 / 调度 / 质量；截图必须来自真实采集结果，并链接最新报告。
3. **目录（Table of Contents）**：锚点链接到各段。
4. **功能特性**：能力清单，逐条能对应到代码或口径。
5. **架构图（mermaid）**：GitHub Actions → 采集 → SQLite → 分析 → 报告 → 回写仓库 → Streamlit。
6. **快速开始**：环境要求 → 安装（uv）→ 环境变量表 → 采集 / 分析 → 启动仪表板。
7. **使用说明**：`collect.py` / `analyze.py` 参数表 + 产物清单。
8. **目录结构**：目录树。
9. **自动化与数据持久化**：`daily-collect.yml` 步骤、回写仓库、`GH_PAT` 配置。
10. **数据与指标口径**：指标定义与缺失处理表。
11. **分析结论**：至少 3 条可量化发现（例如“过去 30 天 Rust 趋势仓库数上升 X%”）。
12. **开发与测试**：`ruff` / `mypy` / `pytest` 命令、覆盖率门槛与当前规模。
13. **文档 / 路线图 / 贡献 / 许可证**：链接 `docs/interview.md` 与 `LICENSE`。

规则：
- 命令块统一用 ```bash + uv 命令；图表用 ```mermaid；参数、产物、指标口径用表格。
- 面试问答可以写在 README，也可以放 `docs/interview.md`（README 必须有入口链接），
  必须覆盖：没有 Trending API 怎么采、Rate Limit 怎么处理、Star Velocity 怎么算、
  与直接看 Trending 页面的区别、为什么适合数据采集 / 数据分析实习、为什么用 uv、
  临时 runner 如何持久化数据。
- 关于 uv 的回答要点：集成 Python 版本管理、虚拟环境、锁文件、工具运行；`uv.lock` 保证本地与 CI 一致；
  `uv run` 消除“忘记激活环境”类问题；安装与解析速度显著快于 pip。
- 简历描述必须量化：采集天数、覆盖仓库数 / 语言数、仪表板访问量、识别出的高速增长仓库数。
- 数字禁止编造：结论必须标注 `snapshot_date`，并能由 `data/processed/` 的产物复现。
