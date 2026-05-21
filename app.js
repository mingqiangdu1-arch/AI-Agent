/* ===== AI 投研分析平台 - 交互逻辑 ===== */

(function () {
  "use strict";

  // API 后端地址（本地开发留空，部署时改为 Render 地址）
  const API_BASE = "";

  const $ = (id) => document.getElementById(id);

  const dom = {
    navItems: document.querySelectorAll(".sidebar-item"),
    tabPages: document.querySelectorAll(".tab-page"),

    // 投研分析
    symbol: $("symbol"),
    period: $("period"),
    interval: $("interval"),
    symbolName: $("symbolName"),
    analyzeBtn: $("analyzeBtn"),
    statusBar: $("statusBar"),
    statusText: $("statusText"),
    pipe1: $("pipe1"),
    pipe2: $("pipe2"),
    pipe3: $("pipe3"),
    resultArea: $("resultArea"),
    emptyState: $("emptyState"),

    // 骨架加载
    skeletonLoader: $("skeletonLoader"),

    // 股票概览
    stockNameDisplay: $("stockNameDisplay"),
    stockCodeDisplay: $("stockCodeDisplay"),
    stockPrice: $("stockPrice"),
    stockChange: $("stockChange"),

    // AI 决策卡
    aiScoreRing: $("aiScoreRing"),
    aiRingFg: $("aiRingFg"),
    aiScoreNum: $("aiScoreNum"),
    aiDecisionLabel: $("aiDecisionLabel"),
    aiConfidence: $("aiConfidence"),
    aiTargetPrice: $("aiTargetPrice"),
    aiStopLoss: $("aiStopLoss"),

    // 价格卡片（保留兼容）
    priceText: $("priceText"),
    priceChange: $("priceChange"),
    trendText: $("trendText"),

    // 策略建议
    actionText: $("actionText"),
    targetPrice: $("targetPrice"),
    stopLoss: $("stopLoss"),

    // 风险
    riskList: $("riskList"),

    // 指标 & 策略
    indicatorList: $("indicatorList"),
    strategyList: $("strategyList"),
    hotTable: $("hotTable"),

    // LLM
    llmSection: $("llmSection"),
    llmMeta: $("llmMeta"),
    llmSummary: $("llmSummary"),
    llmEnhance: $("llmEnhance"),
    llmInsight: $("llmInsight"),
    llmOpportunities: $("llmOpportunities"),
    llmRisks: $("llmRisks"),
    llmToggle: $("llmToggle"),

    // 新闻
    newsSection: $("newsSection"),
    newsSentimentBadge: $("newsSentimentBadge"),
    newsSentimentLabel: $("newsSentimentLabel"),
    newsSentimentConfidence: $("newsSentimentConfidence"),
    newsPositive: $("newsPositive"),
    newsNeutral: $("newsNeutral"),
    newsNegative: $("newsNegative"),
    newsList: $("newsList"),

    // 热榜页
    hotSource: $("hotSource"),
    refreshHotBtn: $("refreshHotBtn"),
    hotlistGrid: $("hotlistGrid"),

    // 研报
    reportSymbol: $("reportSymbol"),
    generateReportBtn: $("generateReportBtn"),
    reportContent: $("reportContent"),

    // 板块推荐
    refreshSectorBtn: $("refreshSectorBtn"),
    sectorGrid: $("sectorGrid"),

    // 设置（只读状态面板）
    settingsBtn: $("settingsBtn"),
    settingsModal: $("settingsModal"),
    closeSettings: $("closeSettings"),
    modelStatus: $("modelStatus"),

    // 走势图
    priceChart: $("priceChart"),

    // 通知
    toastContainer: $("toastContainer"),
  };

  let llmEnabled = false;
  let isAnalyzing = false;

  /* ---------- 工具函数 ---------- */
  function toast(message, type = "info", duration = 3000) {
    const iconMap = {
      success: "fas fa-check-circle",
      error: "fas fa-times-circle",
      warning: "fas fa-exclamation-triangle",
      info: "fas fa-info-circle",
    };
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<i class="${iconMap[type] || iconMap.info}"></i><span>${message}</span>`;
    dom.toastContainer.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      el.addEventListener("animationend", () => el.remove());
    }, duration);
  }

  async function apiPost(url, payload, timeoutMs = 30000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const resp = await fetch(API_BASE + url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try { const err = await resp.json(); msg = err.message || err.detail || msg; } catch (_) {}
        throw new Error(msg);
      }
      return resp.json();
    } catch (e) {
      if (e.name === "AbortError") {
        throw new Error("请求超时，请稍后重试");
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  function formatPrice(v) {
    if (v === null || v === undefined || v === "") return "--";
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : String(v);
  }

  function formatChange(v) {
    if (v === null || v === undefined || v === "") return "--";
    const n = Number(String(v).replace("%", ""));
    if (!Number.isFinite(n)) return String(v);
    return n > 0 ? `+${n.toFixed(2)}%` : `${n.toFixed(2)}%`;
  }

  function changeDir(v) {
    const n = Number(String(v).replace("%", ""));
    if (!Number.isFinite(n)) return "";
    return n > 0 ? "up" : n < 0 ? "down" : "";
  }

  function trendClass(trend) {
    if (!trend) return "sideways";
    if (trend.includes("上涨") || trend.includes("up")) return "up";
    if (trend.includes("下跌") || trend.includes("down")) return "down";
    return "sideways";
  }

  function actionLabel(action) {
    const map = { buy: "买入", sell: "卖出", hold: "观望" };
    return map[action] || action || "--";
  }

  /* ---------- 市场颜色管理：A股红涨绿跌，国际绿涨红跌 ---------- */
  function isAShare(symbol) {
    const s = String(symbol || "").trim().toUpperCase();
    // 6位纯数字（A股代码）
    if (/^\d{6}$/.test(s)) return true;
    // .SS / .SH / .SZ 后缀
    if (/\.(SS|SH|SZ)$/.test(s)) return true;
    // SH/SZ 前缀（如 SH601991）
    if (/^(SH|SZ)\d{6}$/.test(s)) return true;
    return false;
  }

  function applyMarketColors(symbol) {
    const root = document.documentElement;
    if (isAShare(symbol)) {
      // A股：红涨绿跌
      root.style.setProperty("--up-color", "#d4303e");
      root.style.setProperty("--up-bg", "rgba(212,48,62,0.08)");
      root.style.setProperty("--down-color", "#1ca363");
      root.style.setProperty("--down-bg", "rgba(28,163,99,0.08)");
    } else {
      // 国际：绿涨红跌
      root.style.setProperty("--up-color", "#1ca363");
      root.style.setProperty("--up-bg", "rgba(28,163,99,0.08)");
      root.style.setProperty("--down-color", "#d4303e");
      root.style.setProperty("--down-bg", "rgba(212,48,62,0.08)");
    }
  }

  /* ---------- 数字滚动动画 ---------- */
  function animateValue(el, from, to, duration) {
    if (!el) return;
    const start = performance.now();
    const isPrice = Math.abs(to) > 1;
    function tick(now) {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // ease-out
      const val = from + (to - from) * eased;
      el.textContent = isPrice ? formatPrice(val) : formatChange(val);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  /* ---------- 卡片逐步显示 ---------- */
  function cascadeReveal(selector, delay) {
    const els = document.querySelectorAll(selector);
    els.forEach((el, i) => {
      el.style.opacity = "0";
      el.style.transform = "translateY(12px)";
      el.style.transition = "opacity 0.35s ease, transform 0.35s ease";
      setTimeout(() => {
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
      }, (i + 1) * delay);
    });
  }

  /* ---------- Tab 切换 ---------- */
  function switchTab(tabName) {
    dom.navItems.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tabName));
    dom.tabPages.forEach((page) => page.classList.toggle("active", page.id === `${tabName}Tab`));
  }

  dom.navItems.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  /* ---------- Pipeline 状态 ---------- */
  function resetPipeline() {
    [dom.pipe1, dom.pipe2, dom.pipe3].forEach((el) => {
      el.className = "pipe-step";
    });
  }

  function setPipelineStep(stepIdx, state) {
    const el = [dom.pipe1, dom.pipe2, dom.pipe3][stepIdx];
    if (el) el.className = `pipe-step ${state}`;
  }

  /* ---------- 渲染：指标卡片 ---------- */
  function renderMetrics(data) {
    // 根据股票类型设置涨跌颜色
    applyMarketColors(data.symbol);

    const dl = data.decision_layer || {};
    const latestRows = data.latest_rows || [];
    const price = data.price;
    const strategy = data.strategy || {};
    const trendData = data.trend_detail || data.trend || {};
    const trendText = typeof data.trend === "string" ? data.trend : (trendData.trend || "--");

    // 涨跌幅
    let change = null;
    if (latestRows.length >= 2) {
      const prev = latestRows[latestRows.length - 2]?.close;
      const curr = latestRows[latestRows.length - 1]?.close;
      if (prev && curr && prev > 0) change = ((curr - prev) / prev * 100);
    }

    // --- 股票概览卡 ---
    dom.stockNameDisplay.textContent = data.symbol_name || data.symbol || "--";
    dom.stockCodeDisplay.textContent = data.symbol || "--";
    dom.stockPrice.textContent = formatPrice(price);
    if (change !== null) {
      dom.stockChange.textContent = formatChange(change);
      dom.stockChange.className = `ov-change ${changeDir(change)}`;
    }

    // --- AI 决策卡 ---
    const score = dl.score ?? 0;
    dom.aiScoreNum.textContent = score;
    const circumference = 2 * Math.PI * 34; // ~213.6
    const offset = circumference - (score / 100) * circumference;
    dom.aiRingFg.setAttribute("stroke-dashoffset", offset);
    dom.aiRingFg.setAttribute("stroke", score >= 70 ? "var(--up-color)" : score >= 40 ? "var(--accent)" : "var(--down-color)");

    const decision = dl.decision || "观望";
    const badgeClass = decision.includes("看多") || decision.includes("偏多") ? "buy" : decision.includes("看空") || decision.includes("偏空") || decision.includes("回避") ? "sell" : "hold";
    dom.aiDecisionLabel.textContent = decision;
    dom.aiDecisionLabel.className = `ai-badge ${badgeClass}`;
    dom.aiConfidence.textContent = `置信度 ${((dl.confidence || 0.5) * 100).toFixed(0)}%`;
    dom.aiTargetPrice.textContent = formatPrice(strategy.target_price);
    dom.aiStopLoss.textContent = formatPrice(strategy.stop_loss);

    // 保留旧卡兼容（价格+趋势）
    if (dom.priceText) dom.priceText.textContent = formatPrice(price);
    if (change !== null && dom.priceChange) {
      dom.priceChange.textContent = formatChange(change);
      dom.priceChange.className = `change-badge ${changeDir(change)}`;
    }
    if (dom.trendText) {
      dom.trendText.textContent = `趋势 ${trendText}`;
      dom.trendText.className = `metric-sub trend-sub ${trendClass(trendText)}`;
    }

    // 策略
    if (dom.actionText) dom.actionText.textContent = actionLabel(strategy.action);
    if (dom.targetPrice) dom.targetPrice.textContent = `目标价 ${formatPrice(strategy.target_price)}`;
    if (dom.stopLoss) dom.stopLoss.textContent = `止损位 ${formatPrice(strategy.stop_loss)}`;

    // 风险
    dom.riskList.innerHTML = "";
    const risks = data.risk || strategy.risk_factors || [];
    if (risks.length === 0) {
      const span = document.createElement("span");
      span.className = "risk-tag low";
      span.textContent = "暂无风险预警";
      dom.riskList.appendChild(span);
    } else {
      risks.forEach((r) => {
        const span = document.createElement("span");
        span.className = "risk-tag";
        span.textContent = r;
        dom.riskList.appendChild(span);
      });
    }

    // 显示股票名称
    if (data.symbol_name && dom.symbolName) {
      dom.symbolName.textContent = data.symbol_name;
    }
  }

  /* ---------- 渲染：技术指标 ---------- */
  function renderIndicators(indicators) {
    dom.indicatorList.innerHTML = "";
    if (!indicators) return;

    const items = [
      { name: "置信度", value: indicators.confidence, signal: indicators.confidence > 0.7 ? "bullish" : indicators.confidence < 0.4 ? "bearish" : "neutral" },
      { name: "MA 均线", value: indicators.ma, signal: (indicators.ma || "").includes("多") ? "bullish" : (indicators.ma || "").includes("空") ? "bearish" : "neutral" },
      { name: "MACD", value: indicators.macd, signal: (indicators.macd || "").includes("金叉") ? "bullish" : (indicators.macd || "").includes("死叉") ? "bearish" : "neutral" },
      { name: "RSI", value: indicators.rsi, signal: null },
    ];

    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "indicator-item";
      let signalHTML = "";
      if (item.signal) {
        const labelMap = { bullish: "看多", bearish: "看空", neutral: "中性" };
        signalHTML = `<span class="indicator-signal signal-${item.signal}">${labelMap[item.signal]}</span>`;
      }
      div.innerHTML = `
        <span class="indicator-name">${item.name}</span>
        <span class="indicator-value">${item.value ?? "--"}</span>
        ${signalHTML}
      `;
      dom.indicatorList.appendChild(div);
    });
  }

  /* ---------- 渲染：策略详情 ---------- */
  function renderStrategy(strategy) {
    dom.strategyList.innerHTML = "";
    if (!strategy) return;

    const items = [
      { label: "建议动作", val: actionLabel(strategy.action) },
      { label: "关注建议", val: strategy.attention_advice || "--" },
      { label: "关注区间", val: strategy.attention_range || "--" },
      { label: "目标价", val: formatPrice(strategy.target_price) },
      { label: "止损位", val: formatPrice(strategy.stop_loss) },
    ];

    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "strategy-item";
      div.innerHTML = `
        <span class="strategy-label">${item.label}</span>
        <span class="strategy-val">${item.val}</span>
      `;
      dom.strategyList.appendChild(div);
    });
  }

  /* ---------- 渲染：热榜表格 ---------- */
  function renderHotTable(rows) {
    const tbody = dom.hotTable.querySelector("tbody");
    tbody.innerHTML = "";
    if (!Array.isArray(rows) || rows.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="5" style="text-align:center;color:var(--text-muted);">暂无热榜数据</td>';
      tbody.appendChild(tr);
      return;
    }
    rows.forEach((row, idx) => {
      const code = row["代码"] || row.code || "";
      const name = row["名称"] || row.name || "--";
      const hotRaw = parseInt(row["热度"] || row.hot || 0);
      const hotStr = hotRaw > 9999 ? (hotRaw / 10000).toFixed(1) + "万" : hotRaw || "--";
      const chg = row["涨跌幅"] || row.change_pct || "--";
      const chgDir = changeDir(chg);
      const hasCode = code && code !== "--";
      const displayCode = hasCode ? code : "—";
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row["排名"] || idx + 1}</td>
        <td class="font-mono" style="${hasCode ? "" : "color:var(--text-muted);font-style:italic"}">${displayCode}</td>
        <td style="${!hasCode ? "font-weight:600" : ""}">${name}</td>
        <td class="font-mono ${chgDir === "up" ? "text-up" : chgDir === "down" ? "text-down" : ""}">${chgDir ? formatChange(chg) : chg}</td>
        <td class="font-mono">${hotStr}</td>
      `;
      tr.addEventListener("click", () => {
        dom.symbol.value = hasCode ? code : name;
        switchTab("analysis");
        runAnalyze();
      });
      tbody.appendChild(tr);
    });
  }

  /* ---------- 渲染：LLM 解读 ---------- */
  function renderLLM(data) {
    const llm = data.llm || {};
    const enhance = data.llm_enhance || {};
    const trendDetail = data.trend_detail || {};
    const strategy = data.strategy || {};
    const dl = data.decision_layer || {};
    const risks = Array.isArray(data.risk) ? data.risk : [];

    // 元信息
    dom.llmMeta.textContent = llm.model ? `${llm.model}` : "未执行";

    // 格式化的摘要文本
    const rawSummary = llm.analysis_text || llm.summary || "";
    dom.llmSummary.innerHTML = rawSummary
      ? formatMarkdown(rawSummary)
      : '<span class="text-muted">开启侧边栏「AI 增强」后展示深度分析</span>';

    // --- 趋势分析卡片 ---
    const trendDir = (data.trend && typeof data.trend === "string") ? data.trend : (trendDetail.trend || "--");
    const dirClass = trendDir.includes("上涨") ? "up" : trendDir.includes("下跌") ? "down" : "sideways";
    const dirLabel = trendDir.includes("上涨") ? "上涨 ↑" : trendDir.includes("下跌") ? "下跌 ↓" : "震荡 →";
    const tdBadge = document.getElementById("trendBadge");
    tdBadge.textContent = dirLabel;
    tdBadge.className = `ac-badge ${dirClass}`;

    const confidence = (trendDetail.confidence ?? dl.confidence ?? 0.5) * 100;
    const rsiVal = trendDetail.rsi_details?.rsi14 || 50;
    const rsiZone = rsiVal > 70 ? "超买" : rsiVal < 30 ? "超卖" : "中性";
    const rsiColor = rsiVal > 70 ? "var(--down-color)" : rsiVal < 30 ? "var(--up-color)" : "var(--accent)";

    const trendMeters = document.getElementById("trendMeters");
    trendMeters.innerHTML = `
      <div class="ac-meter-row"><span class="ac-meter-label">趋势置信度</span><div class="ac-meter-bar-wrap"><div class="ac-meter-bar" style="width:${confidence}%;background:var(--accent)"></div></div><span class="ac-meter-val">${confidence.toFixed(0)}%</span></div>
      <div class="ac-meter-row"><span class="ac-meter-label">RSI ${rsiVal.toFixed(0)}</span><div class="ac-meter-bar-wrap"><div class="ac-meter-bar" style="width:${rsiVal}%;background:${rsiColor}"></div></div><span class="ac-meter-val">${rsiZone}</span></div>
      <div class="ac-meter-row"><span class="ac-meter-label">MACD</span><span class="ac-meter-val" style="text-align:left;min-width:auto;flex:1">${trendDetail.macd_summary || "--"}</span></div>
      <div class="ac-meter-row"><span class="ac-meter-label">均线</span><span class="ac-meter-val" style="text-align:left;min-width:auto;flex:1">${trendDetail.ma_summary || "--"}</span></div>
    `;

    // --- 投资论点卡片 ---
    const bullish = document.getElementById("bullishFactors");
    const bearish = document.getElementById("bearishFactors");
    bullish.innerHTML = (enhance.opportunities || []).length
      ? (enhance.opportunities || []).slice(0, 3).map((o) => `<li>${o}</li>`).join("")
      : '<li class="text-muted">暂无数据</li>';
    bearish.innerHTML = (enhance.risks || []).length
      ? (enhance.risks || []).slice(0, 3).map((r) => `<li>${r}</li>`).join("")
      : '<li class="text-muted">暂无数据</li>';

    // --- 风险分析卡片 ---
    const riskCount = document.getElementById("riskCountBadge");
    const allRisks = [...risks, ...(enhance.risks || [])].slice(0, 5);
    riskCount.textContent = allRisks.length;
    const riskList = document.getElementById("riskAnalysisList");
    if (allRisks.length) {
      riskList.innerHTML = allRisks.map((r, i) => {
        const level = i === 0 ? "high" : i <= 2 ? "medium" : "low";
        const label = level === "high" ? "高" : level === "medium" ? "中" : "低";
        return `<div class="ac-risk-item"><span class="ac-risk-level ${level}">${label}</span><span class="ac-risk-text">${r}</span></div>`;
      }).join("");
    } else {
      riskList.innerHTML = '<div class="ac-risk-item"><span class="ac-risk-text text-muted">暂无风险数据</span></div>';
    }

    // --- 最终建议卡片 ---
    const decision = dl.decision || "观望";
    const recClass = decision.includes("看多") || decision.includes("偏多") ? "buy" : decision.includes("看空") || decision.includes("偏空") || decision.includes("回避") ? "sell" : "hold";
    const score = dl.score ?? 0;
    const recContent = document.querySelector(".ac-recommend-content");
    recContent.innerHTML = `
      <span class="ac-rec-badge ${recClass}">${decision}</span>
      <div class="ac-rec-details">
        <div class="ac-rec-stat"><span>评分</span><strong>${score} / 100</strong></div>
        <div class="ac-rec-stat"><span>置信度</span><strong>${((dl.confidence || 0.5) * 100).toFixed(0)}%</strong></div>
        <div class="ac-rec-stat"><span>目标价</span><strong>${formatPrice(strategy.target_price)}</strong></div>
        <div class="ac-rec-stat"><span>止损位</span><strong>${formatPrice(strategy.stop_loss)}</strong></div>
      </div>
    `;
  }

  /* --- Markdown 简单格式化 --- */
  function formatMarkdown(text) {
    let html = text
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/^### (.+)$/gm, '<span class="md-h3">$1</span>')
      .replace(/^## (.+)$/gm, '<span class="md-h2">$1</span>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.+)$/gm, '<span style="display:block;padding-left:12px;">• $1</span>')
      .replace(/\n/g, '<br>');
    return html;
  }

  function computeMA(rows, period) {
    const result = [];
    for (let i = 0; i < rows.length; i++) {
      if (i < period - 1) {
        result.push(null);
      } else {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) {
          sum += rows[j].close;
        }
        result.push(+(sum / period).toFixed(2));
      }
    }
    return result;
  }

  /* ---------- 走势图 ---------- */
  let priceChartInstance = null;
  let chartMode = "line"; // "line" | "candle"

  function renderChart(chartData) {
    if (!chartData || chartData.length === 0) return;

    const cs = getComputedStyle(document.documentElement);
    const upHex = cs.getPropertyValue("--up-color").trim() || "#1ca363";
    const downHex = cs.getPropertyValue("--down-color").trim() || "#d4303e";

    const labels = chartData.map((r) => r.date);
    const closes = chartData.map((r) => r.close);
    const volumes = chartData.map((r) => r.volume);
    const ma5 = computeMA(chartData, 5);
    const ma20 = computeMA(chartData, 20);

    // OHLC 数据（K线用）
    const opens = chartData.map((r) => r.open);
    const highs = chartData.map((r) => r.high);
    const lows = chartData.map((r) => r.low);

    const volColors = chartData.map((r, i) => {
      if (i === 0) return "rgba(99, 102, 241, 0.4)";
      return r.close >= chartData[i - 1].close
        ? upHex + "80"
        : downHex + "80";
    });

    if (priceChartInstance) {
      priceChartInstance.destroy();
    }

    const ctx = dom.priceChart.getContext("2d");
    const isCandle = chartMode === "candle";

    // K线自定义插件：在图表上绘制蜡烛图
    const candlePlugin = {
      id: "candlePlugin",
      afterDraw(chart) {
        if (chartMode !== "candle") return;
        const { ctx: cctx, scales: { x, y }, data: { labels: lbls } } = chart;
        const barWidth = x.getPixelForTick(1) - x.getPixelForTick(0);
        const bodyW = Math.max(1, barWidth * 0.5);

        for (let i = 0; i < lbls.length; i++) {
          const o = y.getPixelForValue(opens[i]);
          const c = y.getPixelForValue(closes[i]);
          const h = y.getPixelForValue(highs[i]);
          const l = y.getPixelForValue(lows[i]);
          const cx = x.getPixelForValue(lbls[i]);
          const isUp = closes[i] >= opens[i];

          // 影线（high → low）
          cctx.strokeStyle = isUp ? upHex : downHex;
          cctx.lineWidth = 1;
          cctx.beginPath();
          cctx.moveTo(cx, h);
          cctx.lineTo(cx, l);
          cctx.stroke();

          // 实体（open ↔ close）
          const bodyTop = isUp ? c : o;
          const bodyH = Math.max(1, Math.abs(c - o));
          cctx.fillStyle = isUp ? upHex : downHex;
          cctx.fillRect(cx - bodyW / 2, bodyTop, bodyW, bodyH);
        }
      }
    };

    const lineDatasets = chartMode === "candle"
      ? [
          { label: "MA5", data: ma5, borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0, tension: 0.3, borderDash: [4,2], yAxisID: "y", order: 2 },
          { label: "MA20", data: ma20, borderColor: "#06b6d4", borderWidth: 1.5, pointRadius: 0, tension: 0.3, borderDash: [6,3], yAxisID: "y", order: 3 },
        ]
      : [
          { label: "收盘价", data: closes, borderColor: "#818cf8", backgroundColor: "rgba(129,140,248,0.08)", borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.1, fill: true, yAxisID: "y", order: 1 },
          { label: "MA5", data: ma5, borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0, tension: 0.3, borderDash: [4,2], yAxisID: "y", order: 2 },
          { label: "MA20", data: ma20, borderColor: "#06b6d4", borderWidth: 1.5, pointRadius: 0, tension: 0.3, borderDash: [6,3], yAxisID: "y", order: 3 },
        ];

    const datasets = [
      ...lineDatasets,
      { label: "成交量", data: volumes, type: "bar", backgroundColor: volColors, yAxisID: "y1", order: 4, barPercentage: 0.6 },
    ];

    const plugins = [candlePlugin];
    if (Chart.registry.plugins.get("candlePlugin")) {
      Chart.unregister(Chart.registry.plugins.get("candlePlugin"));
    }
    Chart.register(candlePlugin);

    priceChartInstance = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: true, position: "top",
            labels: { color: "#a5b4c8", font: { size: 11 }, padding: 16, usePointStyle: true, pointStyleWidth: 8 },
          },
          tooltip: {
            backgroundColor: "rgba(15,23,41,0.95)", titleColor: "#f8fafc", bodyColor: "#a5b4c8",
            borderColor: "rgba(99,102,241,0.3)", borderWidth: 1, padding: 12, displayColors: true,
            callbacks: {
              title(items) { return items[0]?.label || ""; },
              label(ctx) {
                const v = ctx.parsed?.y;
                if (v === null || v === undefined) return "";
                const idx = ctx.dataIndex;
                if (chartMode === "candle" && ctx.dataset.label === "MA5") {
                  return `O:${opens[idx]} H:${highs[idx]} L:${lows[idx]} C:${closes[idx]}`;
                }
                const label = ctx.dataset.label;
                if (label === "成交量") return `成交量: ${(v / 10000).toFixed(0)}万`;
                return `${label}: ${Number(v).toFixed(2)}`;
              },
            },
          },
        },
        scales: {
          x: {
            display: true,
            grid: { color: "rgba(148,163,184,0.06)" },
            ticks: { color: "#64748b", font: { size: 10 }, maxRotation: 0, maxTicksLimit: 10 },
          },
          y: {
            display: true, position: "right",
            grid: { color: "rgba(148,163,184,0.06)" },
            ticks: { color: "#64748b", font: { size: 10 }, callback: (v) => v.toFixed(2) },
          },
          y1: {
            display: true, position: "left",
            grid: { display: false },
            ticks: { color: "#64748b", font: { size: 10 }, callback: (v) => (v / 10000).toFixed(0) + "万" },
          },
        },
      },
    });
  }

  /* ---------- 渲染：新闻情绪 ---------- */
  function renderNews(data) {
    const news = data.news;
    if (!news) {
      dom.newsSection.classList.add("hidden");
      return;
    }

    dom.newsSection.classList.remove("hidden");

    // 情绪标签
    const sentiment = news.sentiment || {};
    const sentimentMap = {
      positive: { label: "利好", class: "positive" },
      negative: { label: "利空", class: "negative" },
      neutral: { label: "中性", class: "neutral" },
    };
    const sentimentInfo = sentimentMap[sentiment.label] || sentimentMap.neutral;
    dom.newsSentimentLabel.textContent = sentimentInfo.label;
    dom.newsSentimentLabel.className = `sentiment-label ${sentimentInfo.class}`;
    dom.newsSentimentConfidence.textContent = `置信度 ${((sentiment.confidence || 0.5) * 100).toFixed(0)}%`;

    // 统计
    const dist = sentiment.distribution || {};
    dom.newsPositive.textContent = dist.positive || 0;
    dom.newsNeutral.textContent = dist.neutral || 0;
    dom.newsNegative.textContent = dist.negative || 0;

    // 新闻列表
    const items = news.items || [];
    dom.newsList.innerHTML = "";

    if (items.length === 0) {
      dom.newsList.innerHTML = '<div class="news-empty">暂无相关新闻</div>';
      return;
    }

    items.slice(0, 8).forEach((item) => {
      const div = document.createElement("div");
      div.className = "news-item";

      const sentimentClass = item.sentiment_score > 0.15 ? "positive" : item.sentiment_score < -0.15 ? "negative" : "neutral";
      const sentimentIcon = sentimentClass === "positive" ? "fa-arrow-up" : sentimentClass === "negative" ? "fa-arrow-down" : "fa-minus";

      // 格式化时间
      let timeStr = "";
      if (item.published_at) {
        try {
          const dt = new Date(item.published_at);
          const now = new Date();
          const diffMs = now - dt;
          const diffHours = diffMs / (1000 * 60 * 60);
          if (diffHours < 1) {
            timeStr = `${Math.floor(diffMs / (1000 * 60))}分钟前`;
          } else if (diffHours < 24) {
            timeStr = `${Math.floor(diffHours)}小时前`;
          } else {
            timeStr = `${Math.floor(diffHours / 24)}天前`;
          }
        } catch {
          timeStr = "";
        }
      }

      div.innerHTML = `
        <div class="news-item-header">
          <span class="news-source">${item.source || "--"}</span>
          <span class="news-time">${timeStr}</span>
          <span class="news-sentiment-icon ${sentimentClass}">
            <i class="fas ${sentimentIcon}"></i>
          </span>
        </div>
        <div class="news-title">${item.title || "--"}</div>
        <div class="news-summary">${item.summary || ""}</div>
      `;

      // 点击打开链接
      if (item.url) {
        div.style.cursor = "pointer";
        div.addEventListener("click", () => window.open(item.url, "_blank"));
      }

      dom.newsList.appendChild(div);
    });
  }

  /* ---------- 主分析 ---------- */
  async function runAnalyze() {
    if (isAnalyzing) return;
    isAnalyzing = true;

    const rawSymbol = dom.symbol.value.trim();
    if (!rawSymbol) {
      toast("请输入标的代码", "warning");
      isAnalyzing = false;
      return;
    }
    // 支持输入名称自动转为代码
    let symbol = resolveSymbol(rawSymbol);

    // 如果本地映射未命中且输入包含中文，调用服务端解析
    if (symbol === rawSymbol && /[一-鿿]/.test(rawSymbol)) {
      dom.statusText.textContent = "正在解析名称...";
      dom.statusBar.classList.remove("hidden");
      try {
        const resp = await fetch(`${API_BASE}/resolve_symbol?name=${encodeURIComponent(rawSymbol)}`);
        const data = await resp.json();
        if (data.found && data.code) {
          symbol = data.code;
        } else {
          toast(`无法解析「${rawSymbol}」的股票代码，请手动输入`, "warning");
          dom.statusBar.classList.add("hidden");
          isAnalyzing = false;
          dom.analyzeBtn.disabled = false;
          return;
        }
      } catch (e) {
        toast("名称解析失败，请手动输入股票代码", "warning");
        dom.statusBar.classList.add("hidden");
        isAnalyzing = false;
        dom.analyzeBtn.disabled = false;
        return;
      }
    }

    if (symbol !== rawSymbol) {
      dom.symbol.value = symbol;
      updateSymbolName();
    }

    dom.analyzeBtn.disabled = true;
    dom.emptyState.classList.add("hidden");
    dom.resultArea.classList.add("hidden");
    dom.skeletonLoader.classList.remove("hidden");
    dom.statusBar.classList.remove("hidden");
    dom.statusText.textContent = "正在获取数据...";
    resetPipeline();
    setPipelineStep(0, "active");

    const useLLM = llmEnabled;
    const endpoint = useLLM ? "/llm_analysis" : "/analyze";

    try {
      setTimeout(() => {
        setPipelineStep(0, "done");
        setPipelineStep(1, "active");
        dom.statusText.textContent = "正在分析趋势...";
      }, 800);

      setTimeout(() => {
        setPipelineStep(1, "done");
        setPipelineStep(2, "active");
        dom.statusText.textContent = useLLM ? "正在请求 AI 解读..." : "正在生成策略...";
      }, 1800);

      const payload = {
        symbol,
        provider: "auto",
        period: dom.period.value,
        interval: dom.interval.value,
        hot_limit: 10,
      };

      const result = await apiPost(endpoint, payload, 90000);

      setPipelineStep(2, "done");
      dom.statusText.textContent = "分析完成";

      if (result.status === "error") {
        toast(result.message || result.error || "分析失败", "error");
        dom.statusBar.classList.add("hidden");
        return;
      }

      const data = result.data || {};
      renderMetrics(data);
      window.__lastChartData = data.chart_data;
      renderChart(data.chart_data);
      renderIndicators(data.indicators);
      renderStrategy(data.strategy);
      renderHotTable(data.hot_rank);
      renderNews(data);
      if (useLLM) renderLLM(data);

      dom.skeletonLoader.classList.add("hidden");
      dom.resultArea.classList.remove("hidden");
      dom.emptyState.classList.add("hidden");

      // 卡片逐步显示动画
      cascadeReveal(".overview-row > *", 80);
      cascadeReveal(".chart-section", 50);
      cascadeReveal(".detail-card", 40);
      cascadeReveal(".ai-decision-card", 60);

      if (data.symbol_name) {
        dom.symbolName.textContent = data.symbol_name;
      }

      toast("分析完成", "success");
      setTimeout(() => dom.statusBar.classList.add("hidden"), 2000);

    } catch (err) {
      dom.skeletonLoader.classList.add("hidden");
      setPipelineStep(2, "error");
      dom.statusText.textContent = "请求失败";
      toast(`分析失败: ${err.message}`, "error");
      setTimeout(() => dom.statusBar.classList.add("hidden"), 3000);
    } finally {
      dom.analyzeBtn.disabled = false;
      isAnalyzing = false;
    }
  }

  dom.analyzeBtn.addEventListener("click", runAnalyze);

  /* ---------- LLM 开关 ---------- */
  const aiHint = $("aiHint");
  dom.llmToggle.addEventListener("click", () => {
    llmEnabled = !llmEnabled;
    dom.llmToggle.classList.toggle("active", llmEnabled);
    if (aiHint) { aiHint.textContent = llmEnabled ? "ON" : "OFF"; aiHint.style.display = llmEnabled ? "none" : ""; }
    toast(llmEnabled ? "AI 增强已开启" : "AI 增强已关闭", "info");
  });

  /* ---------- 热榜页 ---------- */
  /* ---------- 热榜页 ---------- */
  let hotAllRows = [];
  let hotCurrentPage = 1;
  let hotPageSize = 20;
  let hotSortKey = "";
  let hotSortAsc = true;

  // 大盘指数
  async function loadMarketIndices() {
    try {
      applyMarketColors("000001");
      const resp = await fetch(API_BASE + "/market_summary");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const indices = data.data || [];
      const container = document.getElementById("marketIndices");
      if (!container) return;
      container.innerHTML = indices.map((idx) => {
        const chg = idx.change_pct ?? 0;
        const chgVal = idx.change ?? 0;
        const color = chg > 0 ? "var(--up-color)" : chg < 0 ? "var(--down-color)" : "var(--text-muted)";
        const sign = chg > 0 ? "+" : "";
        return `<div class="mi-card">
          <div class="mi-name">${idx.name}</div>
          <div class="mi-price">${idx.price ? idx.price.toFixed(2) : "--"}</div>
          <div class="mi-change" style="color:${color}"><span>${sign}${chg.toFixed(2)}%</span> ${chgVal > 0 ? "+" : ""}${chgVal.toFixed(2)}</div>
        </div>`;
      }).join("");
    } catch (e) { /* silent */ }
  }

  function formatVolume(v) {
    if (!v || v === 0) return "--";
    if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
    if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
    return v.toLocaleString();
  }

  function formatAmount(v) {
    if (!v || v === 0) return "--";
    if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
    if (v >= 1e4) return (v / 1e4).toFixed(1) + "万";
    return v.toFixed(0);
  }

  function getAISignal(row) {
    const chg = parseFloat(String(row["涨跌幅"] || row.change_pct || "0").replace("%", ""));
    const hot = parseInt(row["热度"] || row.hot || 0);
    if (!isNaN(chg) && chg > 5) return "bullish";
    if (!isNaN(chg) && chg < -5) return "bearish";
    if (!isNaN(chg) && chg > 2 && hot > 100) return "bullish";
    if (!isNaN(chg) && chg < -2 && hot > 100) return "bearish";
    return "neutral";
  }

  function renderLeaderboard(rows) {
    const grid = dom.hotlistGrid;
    if (!rows || rows.length === 0) {
      grid.innerHTML = '<div class="leaderboard-loading">暂无数据</div>';
      return;
    }

    const totalPages = Math.ceil(rows.length / hotPageSize);
    const start = (hotCurrentPage - 1) * hotPageSize;
    const pageRows = rows.slice(start, start + hotPageSize);

    let html = '<table class="leaderboard-table"><thead><tr>';
    const cols = [
      { key: "排名", label: "#", cls: "td-rank", sortable: true },
      { key: "代码", label: "代码", cls: "td-code", sortable: true },
      { key: "名称", label: "名称", cls: "td-name", sortable: true },
      { key: "最新价", label: "最新价", cls: "td-price", sortable: true },
      { key: "涨跌幅", label: "涨跌幅", cls: "td-chg", sortable: true },
      { key: "成交量", label: "成交量", cls: "td-vol", sortable: true },
      { key: "成交额", label: "成交额", cls: "td-amt", sortable: true },
      { key: "热度", label: "热度", cls: "td-hot", sortable: true },
      { key: "ai", label: "AI", cls: "td-ai", sortable: false },
    ];
    cols.forEach((c) => {
      const sorted = hotSortKey === c.key ? " sorted" : "";
      const arrow = hotSortKey === c.key ? (hotSortAsc ? " ▴" : " ▾") : "";
      html += `<th class="${c.cls}${sorted}" data-sort="${c.sortable ? c.key : ""}">${c.label}<span class="sort-arrow">${arrow}</span></th>`;
    });
    html += '</tr></thead><tbody>';

    pageRows.forEach((row, i) => {
      const code = row["代码"] || row.code || "";
      const name = row["名称"] || row.name || "--";
      const priceRaw = parseFloat(row["最新价"]);
      const price = !isNaN(priceRaw) ? priceRaw : null;
      const chg = row["涨跌幅"] || row.change_pct || "--";
      const chgNum = parseFloat(String(chg).replace("%", ""));
      const chgColor = !isNaN(chgNum) && chgNum > 0 ? "var(--up-color)" : !isNaN(chgNum) && chgNum < 0 ? "var(--down-color)" : "";
      const vol = parseInt(row["成交量"]) || 0;
      const amt = parseFloat(row["成交额"]) || 0;
      const hotVal = parseInt(row["热度"] || row.hot || 0);
      const hotStr = hotVal > 9999 ? (hotVal / 10000).toFixed(1) + "万" : hotVal.toLocaleString() || "--";
      const ai = getAISignal(row);
      const hasCode = code && code !== "--";
      const rank = start + i + 1;

      html += `<tr data-code="${hasCode ? code : ""}" data-name="${name}" data-hascode="${hasCode}">`;
      html += `<td class="td-rank">${rank <= 3 ? ['🥇','🥈','🥉'][rank-1] : rank}</td>`;
      html += `<td class="td-code">${hasCode ? code : "—"}</td>`;
      html += `<td class="td-name">${name}</td>`;
      html += `<td class="td-price">${price ? price.toFixed(2) : "--"}</td>`;
      html += `<td class="td-chg" style="color:${chgColor}">${chg}</td>`;
      html += `<td class="td-vol">${formatVolume(vol)}</td>`;
      html += `<td class="td-amt">${formatAmount(amt)}</td>`;
      html += `<td class="td-hot">${hotStr}</td>`;
      html += `<td class="td-ai"><span class="ai-bullet ${ai}"></span></td>`;
      html += '</tr>';
    });
    html += '</tbody></table>';
    grid.innerHTML = html;

    // 排序表头点击
    grid.querySelectorAll("th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (!key) return;
        if (hotSortKey === key) hotSortAsc = !hotSortAsc;
        else { hotSortKey = key; hotSortAsc = true; }
        sortAndRender();
      });
    });

    // 行点击
    grid.querySelectorAll("tbody tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        const c = tr.dataset.code;
        const n = tr.dataset.name;
        const hc = tr.dataset.hascode === "true";
        dom.symbol.value = hc ? c : n;
        switchTab("analysis");
        if (hc) runAnalyze();
        else { updateSymbolName(); toast(`无法自动识别「${n}」的代码`, "info"); }
      });
    });

    // 分页
    renderPagination(totalPages);
  }

  function sortAndRender() {
    const rows = [...hotAllRows];
    if (hotSortKey) {
      rows.sort((a, b) => {
        let va = a[hotSortKey]; let vb = b[hotSortKey];
        if (hotSortKey === "涨跌幅") { va = parseFloat(String(va).replace("%","")) || 0; vb = parseFloat(String(vb).replace("%","")) || 0; }
        else if (hotSortKey === "最新价" || hotSortKey === "成交量" || hotSortKey === "成交额") { va = parseFloat(va) || 0; vb = parseFloat(vb) || 0; }
        else if (hotSortKey === "热度" || hotSortKey === "排名") { va = parseInt(va) || 0; vb = parseInt(vb) || 0; }
        else { va = String(va || "").toLowerCase(); vb = String(vb || "").toLowerCase(); }
        if (va < vb) return hotSortAsc ? -1 : 1;
        if (va > vb) return hotSortAsc ? 1 : -1;
        return 0;
      });
    }
    renderLeaderboard(rows);
  }

  function renderPagination(total) {
    const pg = document.getElementById("hotPagination");
    if (total <= 1) { pg.innerHTML = ""; return; }
    let h = '';
    for (let i = 1; i <= total; i++) {
      h += `<button class="hot-page-btn${i === hotCurrentPage ? ' active' : ''}" data-page="${i}">${i}</button>`;
    }
    h = `<span class="hot-page-info">${hotCurrentPage} / ${total}</span>` + h;
    pg.innerHTML = h;
    pg.querySelectorAll(".hot-page-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        hotCurrentPage = parseInt(btn.dataset.page);
        sortAndRender();
      });
    });
  }

  async function loadHotlist() {
    applyMarketColors("000001");
    loadMarketIndices();
    dom.hotlistGrid.innerHTML = '<div class="leaderboard-loading">加载中...</div>';
    try {
      const result = await apiPost("/market_hot", {
        limit: hotPageSize === 20 ? 50 : Math.max(50, hotPageSize),
        preferred_source: dom.hotSource.value || "ths",
      }, 60000);
      if (result.status === "error") {
        dom.hotlistGrid.innerHTML = `<div class="leaderboard-loading error">${result.message}</div>`;
        return;
      }
      hotAllRows = result.data || [];
      hotCurrentPage = 1;
      sortAndRender();
    } catch (err) {
      dom.hotlistGrid.innerHTML = `<div class="leaderboard-loading error">请求失败: ${err.message}</div>`;
    }
  }

  // 筛选
  const hotSearch = document.getElementById("hotSearch");
  if (hotSearch) {
    hotSearch.addEventListener("input", () => {
      const q = hotSearch.value.trim().toLowerCase();
      const rows = hotAllRows.filter((r) => {
        const code = String(r["代码"] || r.code || "").toLowerCase();
        const name = String(r["名称"] || r.name || "").toLowerCase();
        return code.includes(q) || name.includes(q);
      });
      hotCurrentPage = 1;
      renderLeaderboard(rows);
    });
  }

  // 分页大小切换
  document.querySelectorAll(".hot-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".hot-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      hotPageSize = parseInt(tab.dataset.limit);
      hotCurrentPage = 1;
      loadHotlist();
    });
  });

  dom.refreshHotBtn.addEventListener("click", loadHotlist);

  /* ---------- 研报中心 ---------- */
  let reportList = [];
  let activeReportId = null;

  async function loadReportList() {
    try {
      const resp = await fetch(API_BASE + "/report_list");
      const data = await resp.json();
      reportList = data.data || [];
      renderReportList();
    } catch (e) { /* silent */ }
  }

  function renderReportList() {
    const container = document.getElementById("reportListItems");
    if (!container) return;
    if (reportList.length === 0) {
      container.innerHTML = '<div class="report-list-empty">暂无研报，生成后自动保存</div>';
      return;
    }
    container.innerHTML = reportList.map((r) => {
      const score = r.score || 50;
      const rec = score >= 65 ? "buy" : score >= 40 ? "hold" : "sell";
      const recLabel = rec === "buy" ? "看多" : rec === "sell" ? "看空" : "观望";
      const active = r.report_id === activeReportId ? " active" : "";
      return `<div class="report-list-item${active}" data-id="${r.report_id}">
        <div class="rli-name">${r.symbol_name || r.symbol}</div>
        <div class="rli-code">${r.symbol}</div>
        <div class="rli-meta"><span class="rli-time">${(r.generated_at || "").slice(0,16)}</span><span class="rli-badge ${rec}">${recLabel} ${score}</span></div>
      </div>`;
    }).join("");

    container.querySelectorAll(".report-list-item").forEach((el) => {
      el.addEventListener("click", () => {
        activeReportId = el.dataset.id;
        renderReportList();
        showReportDetail(el.dataset.id);
      });
    });
  }

  async function showReportDetail(reportId) {
    const detail = document.getElementById("reportDetail");
    const placeholder = document.getElementById("reportPlaceholder");
    detail.classList.add("hidden");
    placeholder.classList.remove("hidden");
    try {
      const resp = await fetch(`${API_BASE}/report_detail/${reportId}`);
      const result = await resp.json();
      if (result.status !== "success" || !result.data) return;
      const d = result.data;
      const report = d.llm_report || {};
      const scores = report.overall_score || {};
      const comp = scores.comprehensive || scores.technical || 50;
      const rec = comp >= 65 ? "buy" : comp >= 40 ? "hold" : "sell";
      const recLabel = rec === "buy" ? "买入" : rec === "sell" ? "卖出" : "观望";
      const ta = report.trend_analysis || {};
      const sa = report.strategy_advice || {};
      const rw = report.risk_warnings || [];
      const risks = (Array.isArray(d.risk) ? d.risk : []).concat(
        Array.isArray(rw) ? rw.map((r) => typeof r === "string" ? r : r.risk || "") : []
      ).slice(0, 5);

      detail.innerHTML = `
        <div class="rd-header">
          <div class="rd-title">${d.symbol_name || d.symbol} 投研报告</div>
          <div class="rd-subtitle">${d.symbol} · ${(d.generated_at || "").slice(0,16)}</div>
          <div class="rd-meta-row">
            <span class="rd-score-badge">${comp}</span>
            <span class="rd-rec-badge ${rec}">${recLabel}</span>
          </div>
        </div>
        ${report.summary ? `<div class="rd-section"><h3>执行摘要</h3><p>${report.summary}</p></div>` : ""}
        ${ta.analysis || ta.ma_status ? `<div class="rd-section"><h3>技术分析</h3>
          ${ta.ma_status ? `<p><strong>均线:</strong> ${ta.ma_status}</p>` : ""}
          ${ta.macd_signal ? `<p><strong>MACD:</strong> ${ta.macd_signal}</p>` : ""}
          ${ta.rsi_zone ? `<p><strong>RSI:</strong> ${ta.rsi_zone}</p>` : ""}
          ${ta.analysis ? `<p>${ta.analysis}</p>` : ""}
        </div>` : ""}
        ${sa.action || sa.advice ? `<div class="rd-section"><h3>策略建议</h3>
          ${sa.action ? `<p><strong>操作:</strong> ${sa.action}</p>` : ""}
          ${sa.position ? `<p><strong>仓位:</strong> ${sa.position}</p>` : ""}
          ${sa.target_price ? `<p><strong>目标价:</strong> ${formatPrice(sa.target_price)}</p>` : ""}
          ${sa.stop_loss ? `<p><strong>止损位:</strong> ${formatPrice(sa.stop_loss)}</p>` : ""}
        </div>` : ""}
        <div class="rd-section"><h3>风险分析</h3>
          ${risks.length ? risks.map((r, i) => {
            const lvl = i === 0 ? "high" : i <= 2 ? "medium" : "low";
            return `<div class="rd-risk-item"><span class="rd-risk-dot ${lvl}"></span>${r}</div>`;
          }).join("") : '<p class="text-muted">暂无风险数据</p>'}
        </div>
        <div class="rd-section"><h3>综合评分</h3>
          <div style="display:flex;gap:24px;">
            <div><span style="font-size:0.7rem;color:var(--text-muted);">技术面</span><br><span style="font-size:1.2rem;font-weight:700;font-family:var(--font-mono);">${scores.technical || "--"}</span></div>
            <div><span style="font-size:0.7rem;color:var(--text-muted);">风险收益</span><br><span style="font-size:1.2rem;font-weight:700;font-family:var(--font-mono);">${scores.risk_reward || "--"}</span></div>
            <div><span style="font-size:0.7rem;color:var(--text-muted);">综合</span><br><span style="font-size:1.2rem;font-weight:700;font-family:var(--font-mono);color:var(--accent);">${comp}</span></div>
          </div>
        </div>`;

      detail.classList.remove("hidden");
      placeholder.classList.add("hidden");
    } catch (e) { /* silent */ }
  }

  async function generateReport() {
    const symbol = resolveSymbol(dom.reportSymbol.value);
    if (!symbol) { toast("请输入标的代码", "warning"); return; }
    dom.reportSymbol.value = symbol;
    const placeholder = document.getElementById("reportPlaceholder");
    placeholder.innerHTML = '<i class="fas fa-spinner fa-spin"></i><p>正在生成研报...</p>';
    placeholder.classList.remove("hidden");
    document.getElementById("reportDetail").classList.add("hidden");

    try {
      const result = await apiPost("/report_hub", { symbol, provider:"auto", period:"6mo", interval:"1d" }, 120000);
      if (result.status === "error") {
        placeholder.innerHTML = `<i class="fas fa-exclamation-circle" style="color:var(--down-color)"></i><p>${result.message || "生成失败"}</p>`;
        return;
      }
      await loadReportList();
      if (reportList.length > 0) {
        activeReportId = reportList[0].report_id;
        renderReportList();
        showReportDetail(activeReportId);
      }
      toast("研报生成完成", "success");
    } catch (err) {
      placeholder.innerHTML = '<i class="fas fa-exclamation-circle" style="color:var(--down-color)"></i><p>生成失败</p>';
    }
  }

  dom.generateReportBtn.addEventListener("click", generateReport);

  /* ---------- 板块推荐 ---------- */
  async function loadSectors() {
    applyMarketColors("000001");
    dom.sectorGrid.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:24px;min-height:120px;display:flex;align-items:center;justify-content:center;"><i class="fas fa-spinner fa-spin"></i>&nbsp;加载中...</div>';
    try {
      const result = await apiPost("/sector_recommend", {});
      if (result.status === "error") {
        dom.sectorGrid.innerHTML = `<div style="text-align:center;color:var(--red);padding:24px;min-height:120px;display:flex;align-items:center;justify-content:center;">${result.message || "加载失败"}</div>`;
        return;
      }
      const data = result.data || {};
      const sectors = data.sectors || [];
      if (sectors.length === 0) {
        dom.sectorGrid.innerHTML = '<div style="color:var(--text-muted);padding:24px;text-align:center;">暂无板块数据</div>';
        return;
      }

      // AI 推荐
      const sorted = [...sectors].sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0));
      const strong = sorted.slice(0, 3), weak = sorted.slice(-3).reverse();
      const stEl = document.getElementById("strongTags"), wkEl = document.getElementById("weakTags");
      if (stEl) stEl.innerHTML = strong.map((s) => `<span class="sai-tag strong"><span class="tag-name">${s.name}</span><span class="tag-chg">${formatChange(s.change_pct)}</span></span>`).join("");
      if (wkEl) wkEl.innerHTML = weak.map((s) => `<span class="sai-tag weak"><span class="tag-name">${s.name}</span><span class="tag-chg">${formatChange(s.change_pct)}</span></span>`).join("");

      dom.sectorGrid.innerHTML = "";
      sectors.forEach((sector, idx) => {
        const chg = sector.change_pct || 0;
        const chgColor = chg > 0 ? "var(--up-color)" : chg < 0 ? "var(--down-color)" : "var(--text-muted)";
        const leading = sector.leading_stock;
        const leadingPct = sector.leading_stock_pct || 0;

        const card = document.createElement("div");
        card.className = "sector-card";
        card.innerHTML = `<div class="sector-card-header">
          <div class="sector-name-row"><span class="sector-rank-dot ${idx < 3 ? 'top3' : ''}"></span><span class="sector-name">${sector.name}</span></div>
          <span class="sector-change-lg" style="color:${chgColor}">${formatChange(chg)}</span>
        </div>
        <div class="sector-stats-row">
          <div class="sector-stat-item"><span class="sector-stat-val">${sector.up_count || 0}</span><span class="sector-stat-lbl">上涨</span></div>
          <div class="sector-stat-item"><span class="sector-stat-val">${sector.down_count || 0}</span><span class="sector-stat-lbl">下跌</span></div>
          ${leading ? `<div class="sector-stat-item"><span class="sector-stat-val">${leading}</span><span class="sector-stat-lbl">领涨</span></div>` : ""}
        </div>
        <div class="sector-sparkline"><canvas id="spark-${idx}" width="200" height="36"></canvas></div>
        ${leading ? `<div class="sector-leading-row"><span>领涨 ${leading}</span><span style="color:${leadingPct > 0 ? 'var(--up-color)' : 'var(--down-color)'};font-family:var(--font-mono);font-weight:600">${formatChange(leadingPct)}</span></div>` : ""}`;

        // 点击板块内股票跳转分析
        card.querySelectorAll(".sector-stock-item").forEach((el) => {
          el.addEventListener("click", (e) => {
            e.stopPropagation();
            const code = el.dataset.code;
            if (code) {
              dom.symbol.value = code;
              switchTab("analysis");
              runAnalyze();
            }
          });
        });

        // 点击板块卡片弹出详情
        card.addEventListener("click", () => {
          showSectorPopup(sector);
        });

        dom.sectorGrid.appendChild(card);
      });
      toast(`已加载 ${sectors.length} 个热门板块`, "success");

      /* ---------- 板块弹窗 ---------- */
      function showSectorPopup(sector) {
        const name = sector.name || "--";
        const chg = sector.change_pct || 0;
        const dir = chg > 0 ? "text-up" : chg < 0 ? "text-down" : "";
        const dirLabel = chg > 0 ? "上涨" : chg < 0 ? "下跌" : "持平";
        const leading = sector.leading_stock;
        const leadingPct = sector.leading_stock_pct;
        const leadingPrice = sector.leading_stock_price;

        document.getElementById("sectorModalTitle").textContent = name + " 板块详情";
        document.getElementById("sectorModalBody").innerHTML = `
          <div style="display:flex;gap:20px;margin-bottom:16px;flex-wrap:wrap;">
            <div style="flex:1;min-width:100px;text-align:center;padding:12px;background:var(--bg-input);border-radius:8px;">
              <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:4px;">涨跌幅</div>
              <div class="${dir}" style="font-size:1.4rem;font-weight:800;font-family:var(--font-mono);">${formatChange(chg)}</div>
            </div>
            <div style="flex:1;min-width:100px;text-align:center;padding:12px;background:var(--bg-input);border-radius:8px;">
              <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:4px;">涨跌家数</div>
              <div style="font-size:1.2rem;font-weight:800;font-family:var(--font-mono);">
                <span class="text-up">${sector.up_count || 0}</span> <span style="color:var(--text-muted);">/</span> <span class="text-down">${sector.down_count || 0}</span>
              </div>
            </div>
          </div>
          ${leading ? `
          <div style="padding:16px;background:var(--bg-input);border-radius:8px;border:1px solid var(--border-light);margin-top:12px;">
            <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:8px;">领涨龙头股</div>
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <div>
                <span style="font-size:1.1rem;font-weight:700;color:var(--text-primary);">${leading}</span>
                ${leadingPrice ? `<span style="font-size:0.88rem;color:var(--text-secondary);margin-left:8px;font-family:var(--font-mono);">¥${leadingPrice.toFixed(2)}</span>` : ""}
              </div>
              <span class="${leadingPct > 0 ? "text-up" : "text-down"}" style="font-size:1rem;font-weight:700;font-family:var(--font-mono);">${formatChange(leadingPct)}</span>
            </div>
            <button style="margin-top:12px;width:100%;" class="secondary-btn" id="sectorLeadBtn">
              <i class="fas fa-search-dollar"></i> 分析「${leading}」
            </button>
          </div>
          ` : ""}
          <p style="margin-top:12px;font-size:0.78rem;color:var(--text-muted);">数据来源：同花顺</p>
        `;

        document.getElementById("sectorModal").classList.remove("hidden");

        // 绑定分析按钮
        const leadBtn = document.getElementById("sectorLeadBtn");
        if (leadBtn) {
          leadBtn.onclick = () => {
            document.getElementById("sectorModal").classList.add("hidden");
            dom.symbol.value = leading;
            switchTab("analysis");
            runAnalyze();
          };
        }
      }
    } catch (err) {
      dom.sectorGrid.innerHTML = `<div style="text-align:center;color:var(--red);padding:24px;min-height:120px;display:flex;align-items:center;justify-content:center;">请求失败: ${err.message}</div>`;
      toast("板块加载失败", "error");
    }
  }

  dom.refreshSectorBtn.addEventListener("click", loadSectors);

  /* ---------- AI 分析卡片折叠 ---------- */
  (function initAccordion() {
    const container = document.getElementById("llmSection");
    if (!container) return;
    container.addEventListener("click", (e) => {
      const header = e.target.closest(".ac-header");
      if (!header) return;
      header.classList.toggle("open");
      const body = header.nextElementSibling;
      if (body && body.classList.contains("ac-body")) {
        body.classList.toggle("open");
      }
    });
    // 默认展开第1和第4张
    container.querySelectorAll(".ac-header").forEach((h, i) => {
      if (i === 0 || i === 3) h.click();
    });
  })();

  /* ---------- 走势图切换 ---------- */
  document.querySelectorAll(".chart-ctrl").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".chart-ctrl").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      chartMode = btn.dataset.type === "candle" ? "candle" : "line";
      // 重新渲染最近一次的图表数据
      const lastData = window.__lastChartData;
      if (lastData) renderChart(lastData);
    });
  });

  /* ---------- 股票代码/名称双向映射 ---------- */
  const STOCK_MAP = {
    "AAPL": "苹果", "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊",
    "NVDA": "英伟达", "TSLA": "特斯拉", "META": "Meta", "NFLX": "奈飞",
    "600519": "贵州茅台", "601318": "中国平安", "000858": "五粮液",
    "000001": "平安银行", "600036": "招商银行", "002594": "比亚迪",
    "300750": "宁德时代",
    "00700": "腾讯控股", "09988": "阿里巴巴", "03690": "美团",
    "01810": "小米集团", "09618": "京东集团",
  };
  // 反向映射：名称 → 代码
  const NAME_TO_CODE = {};
  for (const [code, name] of Object.entries(STOCK_MAP)) {
    NAME_TO_CODE[name] = code;
    NAME_TO_CODE[name.toLowerCase()] = code;
  }

  function resolveSymbol(input) {
    const trimmed = input.trim();
    if (!trimmed) return "";
    // 如果输入的是名称，转为代码
    if (NAME_TO_CODE[trimmed]) return NAME_TO_CODE[trimmed];
    // 如果输入的是代码，返回代码并显示名称
    return trimmed;
  }

  let _nameQueryTimer = 0;
  function updateSymbolName() {
    const val = dom.symbol.value.trim();
    if (!val) {
      dom.symbolName.textContent = "";
      return;
    }
    // 先检查是否是名称输入
    const code = NAME_TO_CODE[val];
    if (code) {
      dom.symbolName.textContent = `${val} → ${code}`;
      return;
    }
    // 检查本地已知代码
    const name = STOCK_MAP[val.toUpperCase()];
    if (name) {
      dom.symbolName.textContent = name;
      return;
    }
    // 后端查询（防抖 400ms）
    clearTimeout(_nameQueryTimer);
    _nameQueryTimer = setTimeout(async () => {
      try {
        const resp = await fetch(`${API_BASE}/resolve_symbol?name=${encodeURIComponent(val)}`);
        const data = await resp.json();
        if (data.found && data.name) {
          dom.symbolName.textContent = data.name;
        } else {
          dom.symbolName.textContent = "";
        }
      } catch (_) {
        dom.symbolName.textContent = "";
      }
    }, 400);
  }

  // 监听输入变化实时更新名称显示
  dom.symbol.addEventListener("input", updateSymbolName);

  /* ---------- 设置弹窗（只读状态） ---------- */
  async function openSettings() {
    dom.settingsModal.classList.remove("hidden");
    dom.modelStatus.textContent = "正在检测...";
    dom.modelStatus.className = "model-status";
    try {
      const result = await apiPost("/model_config", {});
      const diag = result.data?.diagnostic;
      const conf = result.data || {};
      if (diag?.connected) {
        dom.modelStatus.innerHTML = `
          <div style="margin-bottom:8px;font-weight:600;">LLM 服务正常</div>
          <div>模型: ${conf.model || "--"}</div>
          <div>状态: 已连接</div>
        `;
        dom.modelStatus.className = "model-status success";
      } else {
        dom.modelStatus.innerHTML = `
          <div style="margin-bottom:8px;font-weight:600;">LLM 未连接</div>
          <div>${diag?.message || "请在 .env 中配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"}</div>
        `;
        dom.modelStatus.className = "model-status error";
      }
    } catch (err) {
      dom.modelStatus.textContent = `检测异常: ${err.message}`;
      dom.modelStatus.className = "model-status error";
    }
  }

  function closeSettingsModal() {
    dom.settingsModal.classList.add("hidden");
  }

  dom.settingsBtn.addEventListener("click", openSettings);
  dom.closeSettings.addEventListener("click", closeSettingsModal);
  dom.settingsModal.querySelector(".modal-overlay").addEventListener("click", closeSettingsModal);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !dom.settingsModal.classList.contains("hidden")) {
      closeSettingsModal();
    }
  });

  /* ---------- 初始化 ---------- */
  function init() {
    dom.symbol.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runAnalyze();
    });
    dom.reportSymbol.addEventListener("keydown", (e) => {
      if (e.key === "Enter") generateReport();
    });
    // 板块弹窗关闭（一次性绑定）
    document.getElementById("closeSectorModal").addEventListener("click", () => {
      document.getElementById("sectorModal").classList.add("hidden");
    });
    document.getElementById("sectorModal").querySelector(".modal-overlay").addEventListener("click", () => {
      document.getElementById("sectorModal").classList.add("hidden");
    });
    // 全局 Escape 键处理（设置弹窗 + 板块弹窗）
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!dom.settingsModal.classList.contains("hidden")) {
          closeSettingsModal();
        } else {
          document.getElementById("sectorModal").classList.add("hidden");
        }
      }
    });
    loadReportList();
    loadSectors();
    loadMarketIndices();
  }

  init();
})();
