import { useQuery } from "@tanstack/react-query";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

function toJST(ts: string) {
  return new Date(ts).toLocaleString("ja-JP", {
    timeZone: "Asia/Tokyo",
    month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function KpiCard({ label, value, sub, up }: { label:string; value:string; sub?:string; up?:boolean }) {
  return (
    <div className="card" style={{ flex:1, minWidth:140 }}>
      <div style={{ fontSize:11, color:"var(--text-2)", marginBottom:6 }}>{label}</div>
      <div style={{
        fontSize: 22, fontWeight:600, fontFamily:"'IBM Plex Mono', monospace",
        color: up === true ? "var(--green)" : up === false ? "var(--red)" : "var(--text-1)"
      }}>{value}</div>
      {sub && <div style={{ fontSize:11, color:"var(--text-2)", marginTop:4 }}>{sub}</div>}
    </div>
  );
}

function SignalRow({ s }: { s: any }) {
  const badgeCls = s.signal === "BUY" ? "badge-buy" : s.signal === "SELL" ? "badge-sell" : "badge-hold";
  return (
    <tr style={{ borderBottom:"1px solid var(--border-lite)" }}>
      <td style={{ padding:"8px 12px", color:"var(--text-2)", fontSize:11 }}>{toJST(s.timestamp)}</td>
      <td style={{ padding:"8px 12px", fontWeight:500 }}>{s.instrument}</td>
      <td style={{ padding:"8px 12px" }}>
        <span className={`badge ${badgeCls}`}>{s.signal}</span>
      </td>
      <td style={{ padding:"8px 12px", fontFamily:"monospace", fontSize:12 }}>
        {(s.confidence * 100).toFixed(0)}%
      </td>
      <td style={{ padding:"8px 12px", fontFamily:"monospace", fontSize:12 }}>
        {s.entry_price?.toFixed(3) ?? "—"}
      </td>
      <td style={{ padding:"8px 12px", fontFamily:"monospace", fontSize:12, color:"var(--red)" }}>
        {s.stop_loss?.toFixed(3) ?? "—"}
      </td>
      <td style={{ padding:"8px 12px", fontFamily:"monospace", fontSize:12, color:"var(--green)" }}>
        {s.take_profit?.toFixed(3) ?? "—"}
      </td>
    </tr>
  );
}

export default function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ["trade-stats"],
    queryFn: () => fetch("/api/trades/stats").then(r => r.json()),
    refetchInterval: 60_000,
  });

  const { data: equity = [] } = useQuery({
    queryKey: ["equity"],
    queryFn: () => fetch("/api/trades/equity").then(r => r.json()),
    refetchInterval: 60_000,
  });

  const { data: signals = [] } = useQuery({
    queryKey: ["signals"],
    queryFn: () => fetch("/api/signals?limit=20").then(r => r.json()),
    refetchInterval: 30_000,
  });

  const totalPnl    = stats?.total_pnl ?? 0;
  const winRate     = stats ? (stats.win_rate * 100).toFixed(1) + "%" : "—";
  const pf          = stats?.profit_factor?.toFixed(2) ?? "—";
  const totalTrades = stats?.total ?? 0;

  return (
    <div style={{ padding:"1.25rem", height:"100%", display:"flex", flexDirection:"column", gap:"1rem" }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
        <div>
          <h1 style={{ fontSize:18, fontWeight:600 }}>ダッシュボード</h1>
          <div style={{ fontSize:12, color:"var(--text-2)", marginTop:2 }}>
            {new Date().toLocaleString("ja-JP", { timeZone:"Asia/Tokyo" })} 更新
          </div>
        </div>
        <button
          className="primary"
          onClick={() => fetch("/api/signals/scan", { method:"POST" })}
          style={{ fontSize:12 }}
        >
          ▶ 手動スキャン
        </button>
      </div>

      <div style={{ display:"flex", gap:"0.75rem" }}>
        <KpiCard
          label="累積損益"
          value={totalPnl >= 0 ? `+¥${totalPnl.toLocaleString()}` : `-¥${Math.abs(totalPnl).toLocaleString()}`}
          sub="初期資金: ¥1,000,000"
          up={totalPnl >= 0}
        />
        <KpiCard label="勝率"      value={winRate}     sub={`${totalTrades} 取引`} />
        <KpiCard label="PF"        value={pf}           sub="プロフィットファクター" />
        <KpiCard label="最新シグナル"
          value={signals[0]?.signal ?? "—"}
          sub={signals[0]?.instrument ?? ""}
          up={signals[0]?.signal === "BUY" ? true : signals[0]?.signal === "SELL" ? false : undefined}
        />
      </div>

      <div className="card" style={{ flex: "0 0 220px" }}>
        <div style={{ fontSize:12, fontWeight:500, color:"var(--text-2)", marginBottom:"0.75rem" }}>
          エクイティカーブ
        </div>
        {equity.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={equity} margin={{ top:0, right:0, bottom:0, left:0 }}>
              <defs>
                <linearGradient id="eq-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="var(--accent)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--accent)" stopOpacity={0}   />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" tick={false} axisLine={false} tickLine={false} />
              <YAxis
                domain={["auto", "auto"]}
                tick={{ fontSize:10, fill:"var(--text-3)" }}
                axisLine={false} tickLine={false}
                width={70}
                tickFormatter={v => `¥${(v/1000).toFixed(0)}k`}
              />
              <Tooltip
                contentStyle={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:6, fontSize:12 }}
                formatter={(v: number) => [`¥${v.toLocaleString()}`, "資金"]}
              />
              <Area type="monotone" dataKey="equity" stroke="var(--accent)" strokeWidth={1.5} fill="url(#eq-grad)" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height:160, display:"flex", alignItems:"center", justifyContent:"center", color:"var(--text-3)", fontSize:13 }}>
            取引データがありません
          </div>
        )}
      </div>

      <div className="card" style={{ flex:1, minHeight:0, display:"flex", flexDirection:"column" }}>
        <div style={{ fontSize:12, fontWeight:500, color:"var(--text-2)", marginBottom:"0.75rem" }}>
          最新シグナル（日本時間）
        </div>
        <div style={{ overflow:"auto", flex:1 }}>
          <table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead>
              <tr>
                {["日時(JST)","通貨ペア","シグナル","信頼度","エントリー","SL","TP"].map(h => (
                  <th key={h} style={{
                    textAlign:"left", padding:"6px 12px",
                    fontSize:11, fontWeight:500, color:"var(--text-3)",
                    borderBottom:"1px solid var(--border)",
                    whiteSpace:"nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {signals.map((s: any) => <SignalRow key={s.id} s={s} />)}
            </tbody>
          </table>
          {signals.length === 0 && (
            <div style={{ padding:"2rem", textAlign:"center", color:"var(--text-3)", fontSize:13 }}>
              シグナルデータがありません
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
