import { useState } from "react";
import { useForm } from "react-hook-form";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

export default function BacktestPage() {
  const { register, handleSubmit } = useForm({
    defaultValues: {
      instrument: "USD_JPY", granularity: "H1",
      candle_count: 2000, initial_capital: 1000000,
      risk_per_trade: 0.02, sl_atr_mult: 2.0,
      tp_atr_mult: 3.0, confidence_min: 0.33, adx_min: 0,
    }
  });
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);

  const onRun = async (data: any) => {
    setRunning(true); setResult(null); setProgress(0); setMessage("");
    const res = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const reader = res.body!.getReader();
    const dec = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = dec.decode(value);
      for (const line of text.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          const obj = JSON.parse(line.slice(5).trim());
          setProgress(obj.progress);
          setMessage(obj.message);
          if (obj.result) setResult(obj.result);
        } catch { }
      }
    }
    setRunning(false);
  };

  const monthlyData = result?.monthly_returns
    ? Object.entries(result.monthly_returns).map(([k, v]) => ({ month: k, ret: +((v as number) * 100).toFixed(2) }))
    : [];

  const Metric = ({ label, value, up }: any) => (
    <div className="card" style={{ flex: 1 }}>
      <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>{label}</div>
      <div style={{
        fontSize: 18, fontWeight: 600, fontFamily: "monospace",
        color: up === true ? "var(--green)" : up === false ? "var(--red)" : "var(--text-1)"
      }}>
        {value}
      </div>
    </div>
  );

  return (
    <div style={{ padding: "1.25rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
      <h1 style={{ fontSize: 18, fontWeight: 600 }}>バックテスト</h1>

      <div className="card">
        <form onSubmit={handleSubmit(onRun)}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "0.75rem 1.5rem", marginBottom: "1rem" }}>
            {[
              { l: "通貨ペア", n: "instrument", type: "select", opts: ["USD_JPY", "EUR_USD", "GBP_USD"] },
              { l: "時間足", n: "granularity", type: "select", opts: ["M1", "M5", "M15", "H1", "H4", "D", "W", "MN"] },
              { l: "本数", n: "candle_count", type: "number", min: 100, max: 10000, step: "100" },
              { l: "初期資金", n: "initial_capital", type: "number", min: 100000, max: 10000000, step: "100000" },
              { l: "リスク", n: "risk_per_trade", type: "number", step: "0.005", min: 0.005, max: 0.1 },
              { l: "SL倍率", n: "sl_atr_mult", type: "number", step: "0.5", min: 0.5 },
              { l: "TP倍率", n: "tp_atr_mult", type: "number", step: "0.5", min: 0.5 },
              { l: "信頼度（低いほど多くシグナル）", n: "confidence_min", type: "number", step: "0.01", min: 0.0, max: 1.0 },
              { l: "ADX最小（0=全相場）", n: "adx_min", type: "number", min: 0, max: 50 },
            ].map(f => (
              <div key={f.n}>
                <label style={{ display: "block", fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>{f.l}</label>
                {f.type === "select"
                  ? <select {...register(f.n as any)} style={{ width: "100%" }}>
                    {f.opts!.map(o => <option key={o}>{o}</option>)}
                  </select>
                  : <input {...register(f.n as any, { valueAsNumber: true })} type="number"
                    min={f.min} max={f.max} step={f.step ?? 1} style={{ width: "100%" }} />
                }
              </div>
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
            <button type="submit" className="primary" disabled={running}>
              {running ? `${message} (${progress}%)` : "▶ バックテスト実行"}
            </button>
            <span style={{ fontSize: 11, color: "var(--text-3)" }}>
              ※ 信頼度0.33・ADX0 で全シグナルを採用
            </span>
          </div>
        </form>

        {running && (
          <div style={{ marginTop: "0.75rem", height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progress}%`, background: "var(--accent)", transition: "width 0.3s" }} />
          </div>
        )}
      </div>

      {result && !result.error && (
        <>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <Metric label="取引数" value={result.total_trades} />
            <Metric label="勝率" value={`${(result.win_rate * 100).toFixed(1)}%`} up={result.win_rate > 0.5} />
            <Metric label="総損益" value={`¥${result.total_pnl.toLocaleString()}`} up={result.total_pnl > 0} />
            <Metric label="PF" value={result.profit_factor.toFixed(2)} up={result.profit_factor > 1} />
            <Metric label="最大DD" value={`${(result.max_drawdown_pct * 100).toFixed(1)}%`} up={false} />
            <Metric label="シャープ" value={result.sharpe_ratio.toFixed(2)} up={result.sharpe_ratio > 1} />
          </div>

          {monthlyData.length > 0 && (
            <div className="card">
              <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: "0.75rem" }}>月次リターン (%)</div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={monthlyData}>
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: "var(--text-3)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-3)" }} axisLine={false} tickLine={false} />
                  <Tooltip
                    contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", fontSize: 12 }}
                    formatter={(v: number) => [`${v.toFixed(2)}%`, "リターン"]}
                  />
                  <ReferenceLine y={0} stroke="var(--border)" />
                  <Bar dataKey="ret" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
      {result?.error && (
        <div style={{ padding: "1rem", background: "var(--red-dim)", border: "1px solid var(--red)", borderRadius: 6, fontSize: 13, color: "var(--red)" }}>
          エラー: {result.error}
        </div>
      )}
    </div>
  );
}
