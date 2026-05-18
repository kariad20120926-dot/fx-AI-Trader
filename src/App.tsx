import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Dashboard from "./components/Dashboard/Dashboard";
import BacktestPage from "./components/Backtest/BacktestPage";
import SettingsPage from "./components/Settings/SettingsPage";
import ModelPage from "./components/Model/ModelPage";
import ChartPage from "./components/Chart/ChartPage";

type Page = "dashboard" | "chart" | "backtest" | "model" | "settings";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "dashboard", label: "ダッシュボード", icon: "◈" },
  { id: "chart",     label: "チャート",       icon: "▲" },
  { id: "backtest",  label: "バックテスト",   icon: "⟳" },
  { id: "model",     label: "モデル管理",      icon: "◎" },
  { id: "settings",  label: "設定",            icon: "⚙" },
];

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => fetch("/health").then(r => r.json()),
    refetchInterval: 10_000,
    retry: false,
  });

  return (
    <div style={{ display:"flex", height:"100vh", overflow:"hidden" }}>
      <aside style={{
        width: 200,
        background: "var(--bg-panel)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        padding: "1rem 0",
        flexShrink: 0,
      }}>
        <div style={{ padding:"0 1rem 1.25rem", borderBottom:"1px solid var(--border-lite)" }}>
          <div style={{ fontWeight:600, fontSize:15, letterSpacing:".02em" }}>FX AI Trader</div>
          <div style={{ display:"flex", alignItems:"center", gap:6, marginTop:6 }}>
            <span className="live-dot" />
            <span style={{ fontSize:11, color:"var(--text-2)" }}>
              {health ? "API 接続済み" : "API 接続中..."}
            </span>
          </div>
        </div>

        <nav style={{ flex:1, padding:"0.75rem 0" }}>
          {NAV.map(n => (
            <button
              key={n.id}
              onClick={() => setPage(n.id)}
              style={{
                display:"flex", alignItems:"center", gap:10,
                width:"100%", textAlign:"left",
                padding:"9px 1rem",
                border:"none", borderRadius:0,
                background: page === n.id ? "var(--accent-dim)" : "transparent",
                color: page === n.id ? "var(--accent)" : "var(--text-2)",
                fontWeight: page === n.id ? 500 : 400,
                fontSize: 13,
                transition: "background 0.1s, color 0.1s",
              }}
            >
              <span style={{ fontSize:16 }}>{n.icon}</span>
              {n.label}
            </button>
          ))}
        </nav>

        <div style={{ padding:"0.75rem 1rem", borderTop:"1px solid var(--border-lite)", fontSize:11, color:"var(--text-3)" }}>
          v1.0.0
        </div>
      </aside>

      <main style={{ flex:1, overflow:"auto", background:"var(--bg-base)" }}>
        {page === "dashboard" && <Dashboard />}
        {page === "chart"     && <ChartPage />}
        {page === "backtest"  && <BacktestPage />}
        {page === "model"     && <ModelPage />}
        {page === "settings"  && <SettingsPage />}
      </main>
    </div>
  );
}
