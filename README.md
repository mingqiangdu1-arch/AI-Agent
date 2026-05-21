# AI 投研 Agent

**AI 驱动的自动化投研分析工具**

> V2 版本：FastAPI 后端 + 原生 JS 前端。在线体验：[GitHub Pages](https://mingqiangdu1-arch.github.io/AI-Agent)

---

## 项目简介

手动投研需要在行情软件、数据源、指标计算之间反复切换——拉数据、算均线、看 MACD、估目标位、定止损，流程长且重复。

AI 投研 Agent 把这一切压缩为一次点击：选好标的和周期，系统自动走完从行情拉取到策略输出的全部计算，在一个页面上集中呈现结构化结论。面向个人投资者、独立交易员及需要快速获取投研参考的研究者。

---

## 核心功能

### 行情接入

覆盖 A 股、美股及国际市场标的。内置多行情源自动切换——A 股优先国内数据、美股优先国际行情——任一源不可用时无缝回退。支持 1 个月至 2 年回溯周期，日线 / 周线两种粒度。

### 趋势研判

基于均线系统、MACD、RSI 等多维度信号，自动输出趋势方向（上涨 / 下跌 / 震荡）及信赖度评分，同时标注值得关注的技术风险——超买超卖、量价背离、波动率异常等。

### 策略参考

根据趋势结论与市场波幅，自动推算三个关键价位：
- **关注区间** — 入场参考范围
- **目标价位** — 基于波动率的上行预期
- **止损参考** — 动态风险预算

同步梳理标的风险维度，辅助仓位与风控判断。

### 市场热榜

实时展示同花顺 / 东方财富热门个股排名，双源合并（东财提供涨跌幅、雪球提供热度），自动行情补充（最新价/成交量/成交额），数据源不可用时自动生成备选榜单。

### AI 深度解读

可选接入大语言模型（DeepSeek、Qwen、GPT、Gemini 等），生成叙述性投研解读。不启用时基础分析能力不受任何影响。

### 可视化呈现

交互式 K 线图叠加均线系统与成交量，颜色自动适配市场习惯（国内红涨绿跌、海外绿涨红跌）。支持一键导出 Markdown 报告。

---

## 系统架构

```text
                         ┌─────────────────────┐
                         │   GitHub Pages       │
                         │   静态前端 (HTML/JS)  │
                         └────────┬────────────┘
                                  │ HTTP API
                                  ▼
                         ┌─────────────────────┐
                         │   Render / 本地      │
                         │   FastAPI 后端       │
                         └────────┬────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              行情接入        趋势研判       策略参考
          (多源自动切换)   (MA/MACD/RSI)   (目标/止损)
                    │             │             │
                    └─────────────┼─────────────┘
                                  ▼
                            LLM 增强层
                          (可选，失败回退)
```

前后端分离架构。前端为原生 JavaScript SPA，后端为 FastAPI REST API。LLM 增强层为可选环节，失败时自动回退，不中断使用。

---

## Demo

以 **贵州茅台（600519）** 为例，选择近半年日线数据：

| 参数 | 取值 |
|------|------|
| 股票代码 | `600519` |
| 数据源 | 自动 |
| 周期 | 6 个月 |
| 粒度 | 日线 |

**趋势研判输出：**

| 指标 | 结果 |
|------|------|
| 最新收盘价 | 自动获取 |
| 趋势方向 | 上涨 / 下跌 / 震荡 + 信赖度 |
| 均线研判 | 短中期均线排列分析 |
| MACD 研判 | MACD 动能与金叉死叉判断 |
| RSI 研判 | RSI 数值与超买超卖区间 |

**策略参考输出：**

| 决策维度 | 参考建议 |
|----------|----------|
| 操作建议 | buy / sell / hold |
| 关注区间 | 基于波幅计算 |
| 目标价位 | 基于波动率上行预期 |
| 止损参考 | 动态风险预算 |

**界面布局：**

- **概览卡** — 股票名称/代码、最新价、涨跌幅
- **AI 决策卡** — 综合评分环形图、操作建议、目标价/止损位
- **K 线图** — Candlestick + MA5/MA20 均线 + 成交量柱
- **技术指标** — MA/MACD/RSI 详情面板
- **策略详情** — 关注区间、风险因素
- **底部区** — 实时热榜、行情明细、AI 深度分析、新闻聚合
- **板块推荐** — 热门板块涨跌排行
- **研报中心** — LLM 研报生成与缓存

---

## 快速启动

### 方式一：本地运行（推荐）

**1. 安装**

```bash
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

**2. 配置环境变量**

```bash
copy .env.example .env
# 编辑 .env 填入 LLM_API_KEY（可选，不影响基础分析）
```

**3. 启动后端**

```bash
.\.venv\Scripts\python.exe -m uvicorn src.api.app:app --reload --port 8000
```

浏览器访问 `http://localhost:8000`。或双击 `start_api_v2.bat`（Windows）/ `bash start_api_v2.sh`（Linux）。

### 方式二：在线使用

前端已部署至 GitHub Pages，后端托管于 Render。

- 前端地址：`https://mingqiangdu1-arch.github.io/AI-Agent`
- 后端 API：`https://ai-agent-api.onrender.com`

### 方式三：Docker（待支持）

```bash
docker build -t ai-agent .
docker run -p 8000:8000 --env-file .env ai-agent
```

### 常见问题

| 现象 | 解决 |
|------|------|
| 缺少依赖 | 确认已执行 `pip install -r requirements.txt` |
| 端口被占用 | 修改启动命令中的 `--port` 参数 |
| 热榜加载超时 | 等待预热完成后刷新（首次约 30s），后续 < 1s |
| 数据量不足报错 | 将周期调大为 `6mo` 或 `1y` |
| A 股数据为空 | 切换数据源为 stooq 或 mock |
| LLM 未配置 | 不影响基础分析，跳过 AI 深度解读 |

---

## 项目结构

```text
├── frontend_v2/          # 前端（静态 SPA）
│   ├── index.html
│   ├── app.js            # 核心逻辑（API_BASE 配置在此）
│   ├── styles.css
│   └── chart.umd.js
├── src/
│   ├── api/              # FastAPI 路由 + schemas
│   ├── core/             # 配置 + 数据模型
│   ├── services/         # 分析/缓存/LLM/新闻/板块服务
│   └── agents/           # 数据抓取/趋势/策略/热榜/LLM agent
├── prompts/              # LLM 提示词模板
├── requirements.txt
├── render.yaml           # Render 部署配置
├── start_api_v2.bat      # Windows 启动脚本
├── start_api_v2.sh       # Linux 启动脚本
└── .env.example          # 环境变量模板
```

---

## 部署

### GitHub Pages（前端）

推送 `main` 分支后，`.github/workflows/deploy-pages.yml` 自动部署 `frontend_v2/` 到 GitHub Pages。

### Render（后端）

1. 在 [Render](https://render.com) 创建新的 Web Service
2. 连接 GitHub 仓库
3. Render 自动识别 `render.yaml` 配置
4. 在 Render Dashboard 设置 `LLM_API_KEY` 等环境变量

### 环境变量

| 变量 | 必填 | 说明 |
|------|:---:|------|
| `LLM_BASE_URL` | 否 | LLM API 地址（默认 DeepSeek） |
| `LLM_API_KEY` | 否 | LLM API 密钥（不设置则跳过 AI 解读） |
| `LLM_MODEL` | 否 | 模型名称（默认 deepseek-v4-flash） |
| `LLM_TEMPERATURE` | 否 | 生成温度（默认 0.3） |
| `LLM_MAX_TOKENS` | 否 | 最大 token 数（默认 2000） |

---

*免责声明：本产品仅用于投研辅助参考，不构成任何投资建议。*
