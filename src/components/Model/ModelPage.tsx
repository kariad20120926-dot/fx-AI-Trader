// src/components/Model/ModelPage.tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { format } from "date-fns";

export default function ModelPage() {
  const [training, setTraining]   = useState(false);
  const [trainMsg, setTrainMsg]   = useState("");
  const [trainPct, setTrainPct]   = useState(0);
  const [inst,     setInst]       = useState("USD_JPY");
  const [gran,     setGran]       = useState("H1");

  const { data: evals = [], refetch } = useQuery({
    queryKey: ["model-evals"],
    queryFn:  () => fetch("/api/model/evals").then(r => r.json()),
  });

  const onTrain = async () => {
    setTraining(true); setTrainPct(0);
    const res = await fetch(`/api/model/train?instrument=${inst}&granularity=${gran}`, { method:"POST" });
    const reader = res.body!.getReader();
    const dec    = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = dec.decode(value);
      for (const line of text.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const obj = JSON.parse(line.slice(5).trim());
        setTrainPct(obj.progress);
        setTrainMsg(obj.message);
      }
    }
    setTraining(false);
    refetch();
  };

  const chartData = [...evals].reverse().map((e: any) => ({
    date:     format(new Date(e.timestamp), "MM/dd"),
    f1:       +(e.f1_score * 100).toFixed(1),
    accuracy: +(e.accuracy * 100).toFixed(1),
    sharpe:   +e.sharpe_ratio?.toFixed(2),
  }));

  return (
    <div style={{ padding:"1.25rem", display:"flex", flexDirection:"column", gap:"1rem" }}>
      <h1 style={{ fontSize:18, fontWeight:600 }}>モデル管理</h1>

      {/* 学習実行 */}
      <div className="card">
        <div style={{ fontSize:13, fontWeight:500, color:"var(--text-2)", marginBottom:"1rem" }}>
          モデル再学習
        </div>
        <div style={{ display:"flex", gap:12, alignItems:"flex-end", marginBottom:"1rem" }}>
          <div>
            <label style={{ display:"block", fontSize:11, color:"var(--text-2)", marginBottom:4 }}>通貨ペア</label>
            <select value={inst} onChange={e => setInst(e.target.value)} style={{ width:120 }}>
              {["USD_JPY","EUR_USD","GBP_USD"].map(o => <option key={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label style={{ display:"block", fontSize:11, color:"var(--text-2)", marginBottom:4 }}>時間足</label>
            <select value={gran} onChange={e => setGran(e.target.value)} style={{ width:80 }}>
              {["H1","H4","D"].map(o => <option key={o}>{o}</option>)}
            </select>
          </div>
          <button className="primary" onClick={onTrain} disabled={training} style={{ marginBottom:0 }}>
            {training ? `${trainMsg} (${trainPct}%)` : "▶ 再学習開始"}
          </button>
        </div>
        {training && (
          <div style={{ height:4, background:"var(--border)", borderRadius:2, overflow:"hidden" }}>
            <div style={{ height:"100%", width:`${trainPct}%`, background:"var(--green)", transition:"width 0.3s" }} />
          </div>
        )}
      </div>

      {/* 精度推移 */}
      {chartData.length > 0 && (
        <div className="card">
          <div style={{ fontSize:12, color:"var(--text-2)", marginBottom:"0.75rem" }}>精度推移（%）</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <XAxis dataKey="date" tick={{ fontSize:10, fill:"var(--text-3)" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize:10, fill:"var(--text-3)" }} axisLine={false} tickLine={false} domain={[40,100]} />
              <Tooltip contentStyle={{ background:"var(--bg-card)", border:"1px solid var(--border)", fontSize:12 }} />
              <Legend wrapperStyle={{ fontSize:12 }} />
              <Line type="monotone" dataKey="f1"       name="F1スコア" stroke="var(--accent)" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="accuracy" name="正解率"   stroke="var(--green)"  strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 評価履歴テーブル */}
      <div className="card">
        <div style={{ fontSize:12, color:"var(--text-2)", marginBottom:"0.75rem" }}>評価履歴</div>
        <div style={{ overflowX:"auto" }}>
          <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12 }}>
            <thead>
              <tr>
                {["日時","通貨ペア","F1","正解率","勝率","シャープ"].map(h => (
                  <th key={h} style={{ textAlign:"left", padding:"6px 10px", fontSize:11,
                    color:"var(--text-3)", borderBottom:"1px solid var(--border)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {evals.map((e: any, i: number) => (
                <tr key={i} style={{ borderBottom:"1px solid var(--border-lite)" }}>
                  <td style={{ padding:"7px 10px", color:"var(--text-2)" }}>
                    {format(new Date(e.timestamp), "MM/dd HH:mm")}
                  </td>
                  <td style={{ padding:"7px 10px" }}>{e.instrument}</td>
                  <td style={{ padding:"7px 10px", fontFamily:"monospace" }}>{(e.f1_score*100).toFixed(1)}%</td>
                  <td style={{ padding:"7px 10px", fontFamily:"monospace" }}>{(e.accuracy*100).toFixed(1)}%</td>
                  <td style={{ padding:"7px 10px", fontFamily:"monospace" }}>
                    {e.win_rate ? (e.win_rate*100).toFixed(1)+"%" : "—"}
                  </td>
                  <td style={{ padding:"7px 10px", fontFamily:"monospace" }}>
                    {e.sharpe_ratio?.toFixed(2) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
