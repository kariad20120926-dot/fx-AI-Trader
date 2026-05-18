import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createChart } from "lightweight-charts";

const PAIRS = ["USD_JPY", "EUR_USD", "GBP_USD"];
const TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D", "W", "MN"];

export default function ChartPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const tradeLinesRef = useRef<any[]>([]);
  const [pair, setPair] = useState("USD_JPY");
  const [tf, setTf] = useState("H1");
  const [status, setStatus] = useState("loading...");
  const [stats, setStats] = useState<any>(null);
  const [showMarkers, setShowMarkers] = useState(true);
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (id: string) => fetch(`/api/signals/${id}`, { method: "DELETE" }).then(r => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["signals"] }),
  });

  const { data: signals = [] } = useQuery({
    queryKey: ["signals", pair],
    queryFn: () => fetch(`/api/signals?instrument=${pair}&limit=100&hours=720`).then(r => r.json()),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: 420,
      layout: { background: { color: "#141720" }, textColor: "#8890a8" },
      grid: { vertLines: { color: "#1e2540" }, horzLines: { color: "#1e2540" } },
      rightPriceScale: { borderColor: "#2a3050" },
      localization: {
        timeFormatter: (time: any) => {
          if (typeof time === "object" && time.year) {
            return `${time.year}/${String(time.month).padStart(2, '0')}/${String(time.day).padStart(2, '0')}`;
          }
          const d = new Date(time * 1000);
          const y = d.getFullYear();
          const M = String(d.getMonth() + 1).padStart(2, '0');
          const D = String(d.getDate()).padStart(2, '0');
          const h = String(d.getHours()).padStart(2, '0');
          const m = String(d.getMinutes()).padStart(2, '0');
          return `${y}/${M}/${D} ${h}:${m}`;
        }
      },
      timeScale: {
        borderColor: "#2a3050",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: any, tickMarkType: number) => {
          if (typeof time === "object" && time.year) {
            return `${String(time.month).padStart(2, '0')}/${String(time.day).padStart(2, '0')}`;
          }
          const d = new Date(time * 1000);
          const y = d.getFullYear();
          const M = String(d.getMonth() + 1).padStart(2, '0');
          const D = String(d.getDate()).padStart(2, '0');
          const h = String(d.getHours()).padStart(2, '0');
          const m = String(d.getMinutes()).padStart(2, '0');

          if (tickMarkType === 0) return String(y);
          if (tickMarkType === 1 || tickMarkType === 2) return `${M}/${D}`;
          return `${h}:${m}`;
        }
      },
    });
    const series = (chart as any).addCandlestickSeries({
      upColor: "#27c87a", downColor: "#f05a5a",
      borderUpColor: "#27c87a", borderDownColor: "#f05a5a",
      wickUpColor: "#27c87a", wickDownColor: "#f05a5a",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    fetchAndDraw(pair, tf, series, chart);
    return () => {
      tradeLinesRef.current = [];   // 古いシリーズ参照を先にクリア
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (seriesRef.current && chartRef.current) {
      fetchAndDraw(pair, tf, seriesRef.current, chartRef.current);
    }
  }, [pair, tf]);

  useEffect(() => {
    if (!seriesRef.current) return;
    if (!showMarkers) { try { seriesRef.current.setMarkers([]); } catch { } return; }
    applyMarkers(signals);
  }, [showMarkers, signals]);

  function applyMarkers(sigs: any[]) {
    if (!seriesRef.current || !chartRef.current) return;

    const chart = chartRef.current;
    tradeLinesRef.current.forEach(line => { try { chart.removeSeries(line); } catch { } });
    tradeLinesRef.current = [];

    const markers: any[] = [];

    sigs.filter((s: any) => s.signal !== "HOLD").forEach((s: any) => {
      const entryTime = Math.floor(new Date(s.timestamp).getTime() / 1000);
      markers.push({
        time: entryTime as any,
        position: s.signal === "BUY" ? "belowBar" : "aboveBar",
        color: s.signal === "BUY" ? "#27c87a" : "#f05a5a",
        shape: s.signal === "BUY" ? "arrowUp" : "arrowDown",
        text: `${s.signal} ${(s.confidence * 100).toFixed(0)}%`,
      });

      if (s.trade_status === "closed" && s.exit_time && s.exit_price && s.entry_price) {
        const exitTime = Math.floor(new Date(s.exit_time).getTime() / 1000);
        if (exitTime <= entryTime) return; // safeguard

        const isWin = s.pnl_pips > 0;
        markers.push({
          time: exitTime as any,
          position: s.signal === "BUY" ? "aboveBar" : "belowBar",
          color: isWin ? "#27c87a" : "#f05a5a",
          shape: "circle",
          text: `${s.pnl_pips > 0 ? "+" : ""}${s.pnl_pips.toFixed(1)}pip ${isWin ? "✓" : "✗"}`,
        });

        const lineSeries = chart.addLineSeries({
          color: isWin ? "rgba(39, 200, 122, 0.6)" : "rgba(240, 90, 90, 0.6)",
          lineWidth: 2,
          lineStyle: 3,
          crosshairMarkerVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
        });
        lineSeries.setData([
          { time: entryTime, value: s.entry_price },
          { time: exitTime, value: s.exit_price }
        ]);
        tradeLinesRef.current.push(lineSeries);
      }
    });

    markers.sort((a: any, b: any) => a.time - b.time);

    // Deduplicate markers with exactly the same time (LW Charts throws error otherwise)
    const uniqueMarkers = markers.filter((m, i, arr) => i === 0 || m.time !== arr[i - 1].time);

    try { seriesRef.current.setMarkers(uniqueMarkers); } catch { }
  }

  async function fetchAndDraw(p: string, t: string, series: any, chart: any) {
    setStatus("loading...");
    try {
      const res = await fetch(`/api/chart/candles?instrument=${p}&granularity=${t}&count=300`);
      const data = await res.json();
      if (!data.candles?.length) { setStatus("no data"); return; }
      series.setData(data.candles);
      chart.timeScale().fitContent();
      setStats(data.stats);
      setStatus(`${data.candles.length} candles`);
      if (showMarkers) applyMarkers(signals);
    } catch (e) {
      setStatus(`error: ${e}`);
    }
  }

  const latestSig = signals[0];
  const buySignals = signals.filter((s: any) => s.signal === "BUY").length;
  const sellSignals = signals.filter((s: any) => s.signal === "SELL").length;

  const closedTrades = signals.filter((s: any) => s.trade_status === "closed");
  const totalClosed = closedTrades.length;
  const winningTrades = closedTrades.filter((s: any) => s.pnl_pips > 0).length;
  const winRate = totalClosed > 0 ? (winningTrades / totalClosed) * 100 : 0;
  const totalPips = closedTrades.reduce((sum: number, s: any) => sum + s.pnl_pips, 0);
  const avgPips = totalClosed > 0 ? totalPips / totalClosed : 0;

  // BUY / SELL 別勝率
  const closedBuy = closedTrades.filter((s: any) => s.signal === "BUY");
  const closedSell = closedTrades.filter((s: any) => s.signal === "SELL");
  const buyWinRate = closedBuy.length > 0 ? (closedBuy.filter((s: any) => s.pnl_pips > 0).length / closedBuy.length) * 100 : 0;
  const sellWinRate = closedSell.length > 0 ? (closedSell.filter((s: any) => s.pnl_pips > 0).length / closedSell.length) * 100 : 0;

  // 信頼度バケット別勝率
  const confBuckets = [
    { label: "60-70%", min: 0.60, max: 0.70 },
    { label: "70-80%", min: 0.70, max: 0.80 },
    { label: "80-90%", min: 0.80, max: 0.90 },
    { label: "90%+",   min: 0.90, max: 1.01 },
  ];
  const confStats = confBuckets.map(b => {
    const trades = closedTrades.filter((s: any) => s.confidence >= b.min && s.confidence < b.max);
    const wins = trades.filter((s: any) => s.pnl_pips > 0).length;
    return { ...b, total: trades.length, wins, rate: trades.length > 0 ? (wins / trades.length) * 100 : 0 };
  });

  // 累積pip推移（クローズ日時順）
  const sortedClosed = [...closedTrades].sort(
    (a: any, b: any) => new Date(a.exit_time).getTime() - new Date(b.exit_time).getTime()
  );
  let cum = 0;
  const cumSeries = sortedClosed.map((s: any) => ({ pips: (cum += s.pnl_pips) }));

  // SVG累積pip描画用
  function buildCumPath(series: { pips: number }[], w: number, h: number) {
    if (series.length < 2) return { points: "", zero: String(h / 2), lastY: String(h / 2), isPositive: true };
    const pipsArr = series.map(s => s.pips);
    const minP = Math.min(0, ...pipsArr);
    const maxP = Math.max(0, ...pipsArr);
    const range = maxP - minP || 1;
    const pad = 8;
    const toY = (p: number) => pad + ((maxP - p) / range) * (h - pad * 2);
    const toX = (i: number) => (i / (series.length - 1)) * w;
    const points = series.map((s, i) => `${toX(i).toFixed(1)},${toY(s.pips).toFixed(1)}`).join(" ");
    const lastPip = pipsArr[pipsArr.length - 1];
    return { points, zero: toY(0).toFixed(1), lastY: toY(lastPip).toFixed(1), isPositive: lastPip >= 0 };
  }

  return (
    <div style={{ padding: "1.25rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600 }}>チャート</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select value={pair} onChange={e => setPair(e.target.value)} style={{ width: 110 }}>
            {PAIRS.map(p => <option key={p}>{p}</option>)}
          </select>
          <div style={{ display: "flex", gap: 3 }}>
            {TIMEFRAMES.map(t => (
              <button key={t} onClick={() => setTf(t)} style={{
                padding: "4px 9px", fontSize: 12,
                background: tf === t ? "var(--accent)" : "var(--bg-card)",
                color: tf === t ? "#fff" : "var(--text-2)",
                border: `1px solid ${tf === t ? "var(--accent)" : "var(--border)"}`,
                borderRadius: 4,
              }}>{t}</button>
            ))}
          </div>
          <button onClick={() => setShowMarkers(v => !v)} style={{
            padding: "4px 10px", fontSize: 12,
            background: showMarkers ? "var(--green-dim)" : "var(--bg-card)",
            color: showMarkers ? "var(--green)" : "var(--text-3)",
            border: `1px solid ${showMarkers ? "var(--green)" : "var(--border)"}`,
            borderRadius: 4,
          }}>
            {showMarkers ? "シグナル ON" : "シグナル OFF"}
          </button>
          <button onClick={() => seriesRef.current && chartRef.current && fetchAndDraw(pair, tf, seriesRef.current, chartRef.current)} style={{ fontSize: 12, padding: "4px 10px" }}>更新</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <div className="card" style={{ flex: 2, minWidth: 220 }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>最新シグナル</div>
          {latestSig ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className={`badge ${latestSig.signal === "BUY" ? "badge-buy" : latestSig.signal === "SELL" ? "badge-sell" : "badge-hold"}`}>{latestSig.signal}</span>
              <span style={{ fontFamily: "monospace", fontWeight: 500 }}>{latestSig.entry_price?.toFixed(3) ?? "-"}</span>
              <span style={{ fontSize: 11, color: "var(--text-2)" }}>信頼度 {(latestSig.confidence * 100).toFixed(0)}%</span>
              {latestSig.stop_loss && <>
                <span style={{ fontSize: 11, color: "var(--red)" }}>損切 {latestSig.stop_loss.toFixed(3)}</span>
                <span style={{ fontSize: 11, color: "var(--green)" }}>利確 {latestSig.take_profit?.toFixed(3)}</span>
              </>}
            </div>
          ) : <span style={{ color: "var(--text-3)", fontSize: 13 }}>シグナルなし</span>}
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>BUY（30日）</div>
          <div style={{ fontSize: 22, fontWeight: 600, color: "var(--green)" }}>{buySignals}</div>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>SELL（30日）</div>
          <div style={{ fontSize: 22, fontWeight: 600, color: "var(--red)" }}>{sellSignals}</div>
        </div>
        {stats && (
          <div className="card" style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>現在値</div>
            <div style={{ fontSize: 16, fontWeight: 600, fontFamily: "monospace" }}>{stats.latest}</div>
            <div style={{ fontSize: 11, color: stats.change >= 0 ? "var(--green)" : "var(--red)" }}>
              {stats.change >= 0 ? "+" : ""}{stats.change?.toFixed(3)} ({stats.change_pct?.toFixed(2)}%)
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <div className="card" style={{ flex: 1, borderLeft: "3px solid var(--accent)" }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>総トレード数</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{totalClosed}</div>
          <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
            <span style={{ color: "var(--green)" }}>{winningTrades}勝</span>
            {" / "}
            <span style={{ color: "var(--red)" }}>{totalClosed - winningTrades}敗</span>
          </div>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>勝率</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: winRate >= 50 ? "var(--green)" : "var(--red)" }}>
            {winRate.toFixed(1)}%
          </div>
          <div style={{ marginTop: 6, background: "var(--border)", borderRadius: 3, height: 4, overflow: "hidden" }}>
            <div style={{ width: `${winRate}%`, height: "100%", background: winRate >= 50 ? "var(--green)" : "var(--red)", borderRadius: 3, transition: "width 0.4s" }} />
          </div>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>平均Pip</div>
          <div style={{ fontSize: 20, fontWeight: 600, color: avgPips >= 0 ? "var(--green)" : "var(--red)" }}>
            {avgPips > 0 ? "+" : ""}{avgPips.toFixed(1)}
          </div>
          <div style={{ fontSize: 11, color: totalPips >= 0 ? "var(--green)" : "var(--red)", marginTop: 2 }}>
            合計 {totalPips > 0 ? "+" : ""}{totalPips.toFixed(1)} pip
          </div>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 6 }}>BUY / SELL 勝率</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {[
              { label: "BUY", rate: buyWinRate, count: closedBuy.length, color: "var(--green)" },
              { label: "SELL", rate: sellWinRate, count: closedSell.length, color: "var(--red)" },
            ].map(({ label, rate, count, color }) => (
              <div key={label}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                  <span style={{ color }}>{label}</span>
                  <span style={{ color: rate >= 50 ? "var(--green)" : "var(--text-2)", fontWeight: 600 }}>
                    {count > 0 ? `${rate.toFixed(0)}%` : "-"} <span style={{ color: "var(--text-3)", fontWeight: 400 }}>({count})</span>
                  </span>
                </div>
                <div style={{ background: "var(--border)", borderRadius: 3, height: 4, overflow: "hidden" }}>
                  <div style={{ width: `${rate}%`, height: "100%", background: color, borderRadius: 3, opacity: 0.8, transition: "width 0.4s" }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* シグナル勝率分析 */}
      {totalClosed > 0 && (
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {/* 累積pip推移 */}
          <div className="card" style={{ flex: 2, minWidth: 260 }}>
            <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 8 }}>累積Pip推移</div>
            {cumSeries.length >= 2 ? (() => {
              const { points, zero, lastY, isPositive } = buildCumPath(cumSeries, 400, 80);
              const lastPip = cumSeries[cumSeries.length - 1].pips;
              return (
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: isPositive ? "var(--green)" : "var(--red)", marginBottom: 4 }}>
                    {lastPip > 0 ? "+" : ""}{lastPip.toFixed(1)} pip
                  </div>
                  <svg viewBox="0 0 400 80" style={{ width: "100%", height: 80, display: "block" }} preserveAspectRatio="none">
                    <line x1="0" y1={zero} x2="400" y2={zero} stroke="var(--border)" strokeWidth="1" strokeDasharray="4,4" />
                    <polyline points={points} fill="none" stroke={isPositive ? "var(--green)" : "var(--red)"} strokeWidth="2" strokeLinejoin="round" />
                    <circle cx="400" cy={lastY} r="3" fill={isPositive ? "var(--green)" : "var(--red)"} />
                  </svg>
                  <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}>{sortedClosed.length}トレード</div>
                </div>
              );
            })() : (
              <div style={{ color: "var(--text-3)", fontSize: 12, padding: "16px 0" }}>データ不足</div>
            )}
          </div>

          {/* 信頼度バケット別勝率 */}
          <div className="card" style={{ flex: 2, minWidth: 240 }}>
            <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 8 }}>信頼度別 勝率</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {confStats.map(b => (
                <div key={b.label}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
                    <span style={{ color: "var(--text-2)" }}>{b.label}</span>
                    <span>
                      {b.total > 0
                        ? <><span style={{ fontWeight: 600, color: b.rate >= 50 ? "var(--green)" : "var(--red)" }}>{b.rate.toFixed(0)}%</span>
                            <span style={{ color: "var(--text-3)" }}> {b.wins}W/{b.total - b.wins}L</span></>
                        : <span style={{ color: "var(--text-3)" }}>-</span>
                      }
                    </span>
                  </div>
                  <div style={{ background: "var(--border)", borderRadius: 3, height: 6, overflow: "hidden", display: "flex" }}>
                    {b.total > 0 && <>
                      <div style={{ width: `${b.rate}%`, height: "100%", background: "var(--green)", opacity: 0.85 }} />
                      <div style={{ width: `${100 - b.rate}%`, height: "100%", background: "var(--red)", opacity: 0.4 }} />
                    </>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 勝率ヒートマップ (BUY/SELL x 信頼度) */}
          <div className="card" style={{ flex: 2, minWidth: 240 }}>
            <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 8 }}>方向 × 信頼度 勝率</div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "3px 6px", color: "var(--text-3)", fontWeight: 400 }}>区間</th>
                  <th style={{ textAlign: "center", padding: "3px 6px", color: "var(--green)", fontWeight: 600 }}>BUY</th>
                  <th style={{ textAlign: "center", padding: "3px 6px", color: "var(--red)", fontWeight: 600 }}>SELL</th>
                </tr>
              </thead>
              <tbody>
                {confBuckets.map(b => {
                  const buyT = closedBuy.filter((s: any) => s.confidence >= b.min && s.confidence < b.max);
                  const sellT = closedSell.filter((s: any) => s.confidence >= b.min && s.confidence < b.max);
                  const bRate = buyT.length > 0 ? (buyT.filter((s: any) => s.pnl_pips > 0).length / buyT.length) * 100 : null;
                  const sRate = sellT.length > 0 ? (sellT.filter((s: any) => s.pnl_pips > 0).length / sellT.length) * 100 : null;
                  const cell = (rate: number | null, count: number) => (
                    <td style={{ textAlign: "center", padding: "4px 6px" }}>
                      {rate !== null
                        ? <span style={{
                            display: "inline-block", padding: "2px 6px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                            background: rate >= 60 ? "rgba(39,200,122,0.15)" : rate >= 40 ? "rgba(136,144,168,0.1)" : "rgba(240,90,90,0.15)",
                            color: rate >= 60 ? "var(--green)" : rate >= 40 ? "var(--text-2)" : "var(--red)",
                          }}>{rate.toFixed(0)}%<span style={{ fontWeight: 400, fontSize: 10 }}> ({count})</span></span>
                        : <span style={{ color: "var(--text-3)" }}>-</span>
                      }
                    </td>
                  );
                  return (
                    <tr key={b.label} style={{ borderBottom: "1px solid var(--border-lite)" }}>
                      <td style={{ padding: "4px 6px", color: "var(--text-2)" }}>{b.label}</td>
                      {cell(bRate, buyT.length)}
                      {cell(sRate, sellT.length)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: "0.75rem" }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 6, display: "flex", justifyContent: "space-between" }}>
          <span>{pair} / {tf} ({status})</span>
          <span style={{ color: showMarkers ? "var(--green)" : "var(--text-3)" }}>{showMarkers ? "シグナル表示中" : "シグナル非表示"}</span>
        </div>
        <div ref={containerRef} style={{ width: "100%", height: 420, position: "relative" }} />
      </div>

      <div className="card">
        <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: "0.75rem" }}>シグナル履歴（JST）</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["日時(JST)", "シグナル", "信頼度", "エントリー", "損切", "利確", "RR比", "結果", "損益(pip)", "操作"].map(h => (
                  <th key={h} style={{ textAlign: "left", padding: "6px 10px", fontSize: 11, color: "var(--text-3)", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {signals.slice(0, 15).map((s: any) => {
                const isWin = s.trade_status === "closed" && s.pnl_pips > 0;
                const isLoss = s.trade_status === "closed" && s.pnl_pips <= 0;
                const rowBg = isWin ? "rgba(39,200,122,0.04)" : isLoss ? "rgba(240,90,90,0.04)" : undefined;
                return (
                  <tr key={s.id} style={{ borderBottom: "1px solid var(--border-lite)", background: rowBg }}>
                    <td style={{ padding: "6px 10px", color: "var(--text-2)", fontSize: 11, whiteSpace: "nowrap" }}>{s.timestamp}</td>
                    <td style={{ padding: "6px 10px" }}><span className={`badge ${s.signal === "BUY" ? "badge-buy" : s.signal === "SELL" ? "badge-sell" : "badge-hold"}`}>{s.signal}</span></td>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{(s.confidence * 100).toFixed(0)}%</td>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{s.entry_price?.toFixed(3) ?? "-"}</td>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "var(--red)" }}>{s.stop_loss?.toFixed(3) ?? "-"}</td>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "var(--green)" }}>{s.take_profit?.toFixed(3) ?? "-"}</td>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{s.risk_reward?.toFixed(2) ?? "-"}</td>
                    <td style={{ padding: "6px 10px" }}>
                      {s.trade_status === "closed"
                        ? <span style={{
                            display: "inline-block", padding: "2px 7px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                            background: isWin ? "rgba(39,200,122,0.15)" : "rgba(240,90,90,0.15)",
                            color: isWin ? "var(--green)" : "var(--red)",
                          }}>{isWin ? "✓ 勝" : "✗ 負"}</span>
                        : s.trade_status === "open"
                          ? <span style={{ color: "var(--text-3)", fontSize: 11 }}>保有中</span>
                          : <span style={{ color: "var(--text-3)", fontSize: 11 }}>-</span>
                      }
                    </td>
                    <td style={{ padding: "6px 10px", fontFamily: "monospace", color: s.pnl_pips > 0 ? "var(--green)" : s.pnl_pips < 0 ? "var(--red)" : "var(--text-3)" }}>
                      {s.pnl_pips != null ? `${s.pnl_pips > 0 ? "+" : ""}${s.pnl_pips.toFixed(1)}` : "-"}
                    </td>
                    <td style={{ padding: "6px 10px" }}>
                      <button
                        onClick={() => { if (confirm("このシグナルを削除しますか？")) deleteMutation.mutate(s.id); }}
                        style={{ background: "transparent", border: "1px solid var(--red)", color: "var(--red)", borderRadius: 4, padding: "2px 6px", fontSize: 10, cursor: "pointer", opacity: 0.8 }}
                      >
                        削除
                      </button>
                    </td>
                  </tr>
                );
              })}
              {signals.length === 0 && (
                <tr><td colSpan={10} style={{ padding: "2rem", textAlign: "center", color: "var(--text-3)" }}>シグナルデータなし</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
