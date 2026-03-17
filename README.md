# AI 投研 Agent（开发中）

当前进度：已完成 Agent 1（股票数据获取）、Agent 2（趋势分析）和 Agent 3（策略生成）MVP。

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

说明：Streamlit 页面建议在“结果展示模块”阶段再接入，当前测试阶段先保证分析链路稳定。

## 展示模块（G4）

已实现 Streamlit 可视化页面，包含：

- K 线图 + MA10/MA20
- AI 趋势分析报告
- 投资策略建议卡片
- 最近交易数据表

启动方式：

```bash
streamlit run streamlit_app.py
```

页面左侧可切换数据源（`auto/stooq/yahoo/mock`）与股票代码。

## GitHub 发布建议（一键启动）

为降低用户上手成本，仓库已提供 Windows 一键脚本：

- `start_cli.bat`：启动命令行分析模式（会提示输入股票代码）
- `start_web.bat`：启动 Streamlit 页面（依赖已安装时使用）
- `setup_and_start_web.bat`：首次使用推荐，自动创建 `.venv`、安装依赖并启动页面

推荐给新用户的最短路径：

1. 双击 `setup_and_start_web.bat`
2. 浏览器打开 `http://localhost:8501`
3. 在页面左侧输入股票代码并开始分析

## 上传 GitHub 前检查

建议在上传前确认：

- 已忽略本地环境目录（`.venv/`）和缓存文件（见 `.gitignore`）
- `requirements.txt` 可用于安装运行依赖
- 启动入口文件存在：`run.py`、`streamlit_app.py`
- 一键脚本可用：`start_cli.bat`、`start_web.bat`、`setup_and_start_web.bat`
- `README.md` 中包含运行说明与免责声明

推荐上传到仓库的核心文件：

- `README.md`
- `requirements.txt`
- `requirements-dev.txt`（可选）
- `run.py`
- `streamlit_app.py`
- `start_cli.bat`
- `start_web.bat`
- `setup_and_start_web.bat`
- `src/`（全部源码）
- `AI 投研 Agent — PRD（V1） 786e92fe1f9344d98df99f46fe010eb0.md`（可选，产品文档）

## GitHub 上传流程（命令行）

```bash
git init
git add .
git commit -m "feat: MVP of AI research agents with web visualization"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

如果仓库已存在历史提交，先同步远端再推送：

```bash
git remote add origin <你的仓库地址>
git fetch origin
git pull origin main --allow-unrelated-histories
git push -u origin main
```

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

后续将继续接入：

- 分析结果展示模块（CLI 增强 / Web 页面）
