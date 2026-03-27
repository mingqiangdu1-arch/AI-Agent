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

- K 线图 + MA10/MA20/MA30 + 成交量
- AI 趋势分析报告
- 投资策略建议卡片
- 可选 LLM 深度解读（顶部设置面板可配置）
- 最近交易数据表
- 热榜TOP10（接口异常时自动回退）

### 本地启动（推荐）

Windows PowerShell：

```bash
cd "e:\vs code\jy"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

启动成功后浏览器访问：`http://localhost:8501`

页面顶部参数栏可切换数据源（`auto/stooq/yahoo/mock`）与股票代码；分析结果底部固定展示热榜TOP10。

### 网页配置 LLM（可选）

顶部 `⚙️ 设置` 面板支持：

- 开关：启用/关闭 AI 增强分析
- 自动识别：输入 API Key 自动识别服务与默认模型（可关闭）
- 模型服务：内置多家主流 OpenAI 兼容接口预设
- 可配置项：`Base URL`、模型名称、`API Key`、`Temperature`、`Max Tokens`
- 连通性测试：支持在保存前先测试接口可用性

增强体验（不偏离 V1 单标的分析范围）：

- API 连通状态徽标（未测试 / 正常 / 异常）
- 连通性测试成功后可自动应用识别到的服务配置
- 股票名称解析缓存（降低重复请求与页面延迟）
- 一键下载分析报告（Markdown）
- 额外展示 20 日波动率与量比（5日/20日）

当前内置预设：

- 阿里百炼(Qwen)
- OpenAI
- Gemini
- DeepSeek
- Moonshot(Kimi)
- 智谱(GLM)
- OpenRouter
- 硅基流动(SiliconFlow)
- 火山方舟(Ark)
- 自定义(OpenAI兼容)

说明：

- 不开启 LLM 时，系统保持原有基础分析（MA/MACD/RSI + 策略生成）
- 开启 LLM 但接口异常时，自动回退基础分析，不影响主流程
- API Key 仅在当前会话内使用，代码中不硬编码密钥
- 若 AI 解读内容过短，优先提高设置面板 `Max Tokens`（例如 1200-2400）并重试

推荐环境变量：

```bash
# 阿里百炼
DASHSCOPE_API_KEY=your_key

# OpenAI
OPENAI_API_KEY=your_key

# Gemini
GEMINI_API_KEY=your_key
# 或
GOOGLE_API_KEY=your_key

# DeepSeek
DEEPSEEK_API_KEY=your_key

# Moonshot
MOONSHOT_API_KEY=your_key

# 智谱
ZHIPUAI_API_KEY=your_key

# OpenRouter
OPENROUTER_API_KEY=your_key

# 硅基流动
SILICONFLOW_API_KEY=your_key

# 火山方舟
ARK_API_KEY=your_key
```

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

4. 同花顺热榜提示不可用：

```bash
.\.venv\Scripts\python.exe -m pip install akshare
```

若接口临时波动，页面会保留主分析结果并提示热榜失败原因。

### 在线部署建议（可选）

可使用 Streamlit Community Cloud：

1. 将项目推送到 GitHub
2. 在 Streamlit Cloud 选择该仓库与分支
3. `Main file path` 填 `streamlit_app.py`
4. 部署完成后会得到公开访问链接


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

## 6. 支持范围与建议

当前支持的股票输入：

- A 股：`000001`、`600519`、`000554.SZ`、`600519.SS`、`600519.SH`
- 美股及其他 Yahoo 可识别代码：如 `AAPL`、`MSFT`

数据源建议：

- A 股优先使用 `auto`（已优化为优先 AkShare，再回退 Yahoo/Stooq）
- 若 A 股仍失败，可手动切换 `--provider akshare`
- 美股优先使用 `auto` / `yahoo`
- 离线调试可使用 `mock`

说明：

- `akshare` 当前面向 A 股 6 位代码
- `stooq` 对部分 A 股代码覆盖有限，建议作为回退数据源
