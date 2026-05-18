import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

export default function SettingsPage() {
  const { register, handleSubmit, reset, formState: { isDirty } } = useForm();
  const [oandaResult,   setOandaResult]   = useState<any>(null);
  const [tdResult,      setTdResult]      = useState<any>(null);
  const [discordResult, setDiscordResult] = useState<any>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/api/settings").then(r => r.json()).then(data => reset(data));
  }, []);

  const onSave = async (data: any) => {
    setSaving(true);
    await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    });
    setSaving(false);
    reset(data);
  };

  const Field = ({ label, name, type = "text", placeholder = "", hint = "" }: any) => (
    <div style={{ marginBottom:"1rem" }}>
      <label style={{ display:"block", fontSize:12, color:"var(--text-2)", marginBottom:5 }}>{label}</label>
      <input {...register(name)} type={type} placeholder={placeholder} style={{ width:"100%", maxWidth:420 }} />
      {hint && <div style={{ fontSize:11, color:"var(--text-3)", marginTop:4 }}>{hint}</div>}
    </div>
  );

  const NumField = ({ label, name, min, max, step = "0.01" }: any) => (
    <div style={{ marginBottom:"1rem" }}>
      <label style={{ display:"block", fontSize:12, color:"var(--text-2)", marginBottom:5 }}>{label}</label>
      <input {...register(name)} type="number" min={min} max={max} step={step} style={{ width:120 }} />
    </div>
  );

  const TestBtn = ({ label, onClick, result }: any) => (
    <div style={{ display:"flex", alignItems:"center", gap:12 }}>
      <button type="button" onClick={onClick} style={{ fontSize:12 }}>{label}</button>
      {result && (
        <span style={{ fontSize:12, color: result.success ? "var(--green)" : "var(--red)" }}>
          {result.success ? "✓" : "✗"} {result.message}
        </span>
      )}
    </div>
  );

  return (
    <div style={{ padding:"1.25rem", maxWidth:720 }}>
      <h1 style={{ fontSize:18, fontWeight:600, marginBottom:"1.5rem" }}>設定</h1>
      <form onSubmit={handleSubmit(onSave)}>

        <div className="card" style={{ marginBottom:"1rem" }}>
          <div style={{ fontSize:13, fontWeight:500, marginBottom:"1rem", color:"var(--text-2)" }}>
            Twelve Data API（リアルタイムデータ）
          </div>
          <Field
            label="API キー"
            name="twelvedata_api_key"
            type="password"
            placeholder="your_api_key_here"
            hint="https://twelvedata.com で無料取得（登録のみ）"
          />
          <TestBtn
            label="接続テスト"
            onClick={async () => { setTdResult(null); setTdResult(await fetch("/api/settings/test-twelvedata", { method:"POST" }).then(r=>r.json())); }}
            result={tdResult}
          />
        </div>

        <div className="card" style={{ marginBottom:"1rem" }}>
          <div style={{ fontSize:13, fontWeight:500, marginBottom:"1rem", color:"var(--text-2)" }}>
            OANDA API（オプション）
          </div>
          <Field label="API キー" name="oanda_api_key" type="password" placeholder="xxxx-xxxx-xxxx-xxxx" />
          <Field label="アカウント ID" name="oanda_account_id" placeholder="001-001-xxxxxxx-001" />
          <div style={{ marginBottom:"1rem" }}>
            <label style={{ display:"block", fontSize:12, color:"var(--text-2)", marginBottom:5 }}>環境</label>
            <select {...register("oanda_environment")} style={{ width:160 }}>
              <option value="practice">デモ (practice)</option>
              <option value="live">本番 (live)</option>
            </select>
          </div>
          <TestBtn
            label="接続テスト"
            onClick={async () => { setOandaResult(null); setOandaResult(await fetch("/api/settings/test", { method:"POST" }).then(r=>r.json())); }}
            result={oandaResult}
          />
        </div>

        <div className="card" style={{ marginBottom:"1rem" }}>
          <div style={{ fontSize:13, fontWeight:500, marginBottom:"1rem", color:"var(--text-2)" }}>
            Discord 通知
          </div>
          <Field
            label="Webhook URL"
            name="discord_webhook_url"
            type="password"
            placeholder="https://discord.com/api/webhooks/..."
            hint="チャンネル設定 → 連携サービス → ウェブフック → URLをコピー"
          />
          <TestBtn
            label="テスト送信"
            onClick={async () => { setDiscordResult(null); setDiscordResult(await fetch("/api/settings/test-discord", { method:"POST" }).then(r=>r.json())); }}
            result={discordResult}
          />
        </div>

        <div className="card" style={{ marginBottom:"1rem" }}>
          <div style={{ fontSize:13, fontWeight:500, marginBottom:"1rem", color:"var(--text-2)" }}>
            LINE Notify 通知
          </div>
          <Field
            label="アクセストークン"
            name="line_notify_token"
            type="password"
            placeholder="LINE Notify トークン"
            hint="https://notify-bot.line.me/my/ → トークンを発行"
          />
        </div>

        <div className="card" style={{ marginBottom:"1rem", borderLeft:"3px solid var(--accent)" }}>
          <div style={{ fontSize:13, fontWeight:500, marginBottom:"0.75rem", color:"var(--text-1)" }}>
            PC OFF 時もクラウドから通知を受け取る（GitHub Actions）
          </div>
          <div style={{ fontSize:12, color:"var(--text-2)", lineHeight:1.8 }}>
            <p style={{ marginBottom:"0.5rem" }}>
              このアプリを起動していない（PC を切っている）場合でも通知を受け取るには、<br />
              GitHub リポジトリに以下のシークレットを登録してください。
            </p>
            <div style={{ background:"var(--bg-base)", border:"1px solid var(--border)", borderRadius:6, padding:"0.75rem 1rem", fontFamily:"monospace", fontSize:11, marginBottom:"0.75rem" }}>
              <div style={{ marginBottom:4 }}>
                <span style={{ color:"var(--accent)" }}>①</span>{" "}
                GitHubリポジトリ → <strong>Settings</strong> → <strong>Secrets and variables</strong> → <strong>Actions</strong>
              </div>
              <div style={{ marginBottom:4 }}>
                <span style={{ color:"var(--accent)" }}>②</span>{" "}
                「New repository secret」をクリック
              </div>
              <div style={{ marginBottom:4 }}>
                <span style={{ color:"var(--green)" }}>DISCORD_WEBHOOK_URL</span>{" "}
                = 上記の Webhook URL
              </div>
              <div>
                <span style={{ color:"var(--green)" }}>LINE_NOTIFY_TOKEN</span>{" "}
                = 上記の LINE アクセストークン
              </div>
            </div>
            <p style={{ fontSize:11, color:"var(--text-3)" }}>
              設定後は GitHub Actions が毎時30分ごとに自動でスキャンし、<br />
              BUY / SELL シグナル検出時のみ Discord・LINE に通知が届きます。<br />
              <code>.github/workflows/fx-cloud-notify.yml</code> で実行スケジュールを変更できます。
            </p>
          </div>
        </div>

        <div className="card" style={{ marginBottom:"1.5rem" }}>
          <div style={{ fontSize:13, fontWeight:500, marginBottom:"1rem", color:"var(--text-2)" }}>
            取引パラメーター
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:"0 2rem" }}>
            <NumField label="1取引リスク" name="risk_per_trade" min={0.005} max={0.10} step={0.005} />
            <NumField label="初期資金 (円)" name="initial_capital" min={100000} max={100000000} step={100000} />
            <NumField label="SL 倍率 (ATR)" name="sl_atr_mult" min={0.5} max={5} step={0.5} />
            <NumField label="TP 倍率 (ATR)" name="tp_atr_mult" min={0.5} max={10} step={0.5} />
            <NumField label="最低信頼度" name="confidence_min" min={0.0} max={0.9} step={0.01} />
            <NumField label="ADX 最小値" name="adx_min" min={0} max={50} step={5} />
          </div>
        </div>

        <div style={{ display:"flex", gap:10 }}>
          <button type="submit" className="primary" disabled={!isDirty || saving}>
            {saving ? "保存中..." : "設定を保存"}
          </button>
          {!isDirty && <span style={{ fontSize:12, color:"var(--text-3)", alignSelf:"center" }}>保存済み</span>}
        </div>
      </form>
    </div>
  );
}
