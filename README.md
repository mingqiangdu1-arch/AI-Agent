# AI 投研 Agent

当前进度：已完成 V1 的 4 个核心模块（数据获取、趋势分析、策略生成、结果展示）。

## 测试阶段运行方式（推荐）

当前阶段建议优先使用 `run.py` 进行联调，原因：

- 启动参数更少，默认即可跑通完整链路
- 默认真实数据源（`auto`），并支持一键切换
- 方便快速验证 Agent 1/2/3 的逻辑正确性

运行完整链路（默认 strategy + auto）：

```bash
python run.py
```

不传 `--symbol` 时，程序会在运行时提示输入股票代码。

切换到真实数据（推荐 stooq）：

```bash
python run.py --symbol 600519.SS --provider stooq --module strategy
```

说明：当前已支持 CLI 与 Streamlit 两种运行方式。

## 展示模块（G4）

已实现 Streamlit 可视化页面，包含：

- K 线图 + MA10/MA20
- AI 趋势分析报告
- 投资策略建议卡片
- 最近交易数据表

### 本地启动（推荐）

Windows PowerShell：

```bash
cd "e:\vs code\jy"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

启动成功后浏览器访问：`http://localhost:8501`

页面左侧可切换数据源（`auto/stooq/yahoo/mock`）与股票代码。

### 常见问题

1. 双击运行 `streamlit_app.py` 报错：
必须使用 `streamlit run` 启动，不能直接按普通 Python 脚本运行。

2. 报错缺少 `streamlit` 或 `plotly`：

```bash
.\.venv\Scripts\python.exe -m pip install streamlit plotly
```

3. 8501 端口被占用：

```bash
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8502
```

### 在线部署建议（可选）

可使用 Streamlit Community Cloud：

1. 将项目推送到 GitHub
2. 在 Streamlit Cloud 选择该仓库与分支
3. `Main file path` 填 `streamlit_app.py`
4. 部署完成后会得到公开访问链接

## GitHub 发布建议（一键启动）

为降低用户上手成本，仓库已提供 Windows 一键脚本：

- `start_cli.bat`：启动命令行分析模式（会提示输入股票代码）
- `start_web.bat`：启动 Streamlit 页面（依赖已安装时使用）
- `setup_and_start_web.bat`：首次使用推荐，自动创建 `.venv`、安装依赖并启动页面

推荐给新用户的最短路径：

1. 双击 `setup_and_start_web.bat`
2. 浏览器打开 `http://localhost:8501`
3. 在页面左侧输入股票代码并开始分析

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 运行 Agent 1

```bash
python src/main.py AAPL
```

## 3. 运行 Agent 2（趋势分析）

```bash
python src/main.py 600519.SS --module trend --provider stooq
```

JSON 输出：

```bash
python src/main.py AAPL --module trend --provider mock --format json
```

## 4. 运行 Agent 3（策略生成）

```bash
python src/main.py 600519.SS --module strategy --provider stooq
```

JSON 输出：

```bash
python src/main.py AAPL --module strategy --provider mock --format json
```

示例（输出 JSON）：

```bash
python src/main.py 600519.SS --period 1y --interval 1d --format json --limit 10
```

如遇 Yahoo 限流，可显式切换到 Stooq：

```bash
python src/main.py AAPL --provider stooq
```

如在本地网络受限，可使用离线调试数据：

```bash
python src/main.py AAPL --provider mock
```

## 5. 当前实现范围

- 输入股票代码
- 获取历史开高低收量（OHLCV）
- 输出标准化时间序列（表格或 JSON）
- 双数据源兜底（`auto`: Yahoo -> Stooq）
- 离线调试数据源（`mock`）
- 基于 MA / MACD / RSI 的趋势研判
- 结构化风险提示输出
- 基于趋势结果生成关注区间、目标价、止损价
- Streamlit 可视化展示（K 线图、分析报告、策略卡片、数据表）
