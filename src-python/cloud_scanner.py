# -*- coding: utf-8 -*-
"""
cloud_scanner.py
PC が OFF のときでも Discord / LINE に通知を届けるクラウド実行専用スクリプト。
GitHub Actions のスケジュール実行から呼び出すことを想定。

・ML モデル不要（ルールベース: RSI + EMA クロス + MACD ヒストグラム）
・データベース不要（SQLite 参照なし）
・yfinance で無料取得（API キー不要）

必要な環境変数（GitHub Secrets に設定）:
  DISCORD_WEBHOOK_URL   Discord Webhook URL
  LINE_NOTIFY_TOKEN     LINE Notify トークン（どちらか片方だけでも可）
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

# ── 監視ペア設定 ──────────────────────────────────────────────────────────────
WATCH_LIST = [
    {"yf_symbol": "USDJPY=X", "instrument": "USD_JPY", "is_jpy": True},
    {"yf_symbol": "EURUSD=X", "instrument": "EUR_USD", "is_jpy": False},
    {"yf_symbol": "GBPUSD=X", "instrument": "GBP_USD", "is_jpy": False},
]

# ── インジケーター設定 ────────────────────────────────────────────────────────
RSI_PERIOD   = 14
EMA_FAST     = 20
EMA_SLOW     = 50
MACD_FAST    = 12
MACD_SLOW    = 26
MACD_SIGNAL  = 9
ATR_PERIOD   = 14
SL_MULT      = 2.0
TP_MULT      = 3.0

# シグナル条件スコア閾値（3条件中いくつ満たせば通知するか）
MIN_SCORE = 2


# ── 市場時間チェック ──────────────────────────────────────────────────────────
def is_market_open() -> bool:
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    wd  = now.weekday()
    if wd == 6:                          # 日曜
        return False
    if wd == 5 and now.hour >= 6:        # 土曜 6:00 JST 以降
        return False
    if wd == 0 and now.hour < 6:         # 月曜 6:00 JST 未満
        return False
    return True


# ── データ取得 ────────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, period: str = "5d", interval: str = "1h"):
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        # MultiIndex 対応（yfinance v0.2+）
        if hasattr(df.columns, "levels"):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        return df
    except Exception as e:
        print(f"[ERROR] データ取得失敗 {symbol}: {e}")
        return None


# ── テクニカル指標 ────────────────────────────────────────────────────────────
def calc_rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def calc_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = (
        (high - low)
        .combine((high - prev_close).abs(), max)
        .combine((low  - prev_close).abs(), max)
    )
    return tr.rolling(period).mean()


# ── シグナル検出 ──────────────────────────────────────────────────────────────
def detect_signal(df) -> dict | None:
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    rsi        = calc_rsi(close, RSI_PERIOD)
    ema_fast   = close.ewm(span=EMA_FAST,    adjust=False).mean()
    ema_slow   = close.ewm(span=EMA_SLOW,    adjust=False).mean()
    macd_line  = (close.ewm(span=MACD_FAST,  adjust=False).mean()
                - close.ewm(span=MACD_SLOW,  adjust=False).mean())
    sig_line   = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    macd_hist  = macd_line - sig_line
    atr        = calc_atr(high, low, close, ATR_PERIOD)

    rsi_now    = rsi.iloc[-1]
    ema_f_now  = ema_fast.iloc[-1]
    ema_s_now  = ema_slow.iloc[-1]
    hist_now   = macd_hist.iloc[-1]
    hist_prev  = macd_hist.iloc[-2]
    atr_now    = atr.iloc[-1]
    price      = close.iloc[-1]

    # BUY 条件: RSI 売られ過ぎ / 上昇トレンド / MACD 反転上向き
    buy_cond = [
        rsi_now < 45,
        ema_f_now > ema_s_now,
        hist_now > hist_prev and hist_now < 0,  # ヒストグラム底打ち
    ]
    # SELL 条件: RSI 買われ過ぎ / 下降トレンド / MACD 反転下向き
    sell_cond = [
        rsi_now > 55,
        ema_f_now < ema_s_now,
        hist_now < hist_prev and hist_now > 0,  # ヒストグラム天井打ち
    ]

    buy_score  = sum(buy_cond)
    sell_score = sum(sell_cond)

    if buy_score >= MIN_SCORE:
        return {
            "signal":      "BUY",
            "confidence":  buy_score / 3,
            "entry_price": price,
            "stop_loss":   price - atr_now * SL_MULT,
            "take_profit": price + atr_now * TP_MULT,
            "risk_reward": TP_MULT / SL_MULT,
            "rsi":         rsi_now,
            "score":       buy_score,
        }
    if sell_score >= MIN_SCORE:
        return {
            "signal":      "SELL",
            "confidence":  sell_score / 3,
            "entry_price": price,
            "stop_loss":   price + atr_now * SL_MULT,
            "take_profit": price - atr_now * TP_MULT,
            "risk_reward": TP_MULT / SL_MULT,
            "rsi":         rsi_now,
            "score":       sell_score,
        }
    return None


# ── 通知送信 ──────────────────────────────────────────────────────────────────
def send_discord(webhook_url: str, instrument: str, sig: dict) -> bool:
    color  = 0x27C87A if sig["signal"] == "BUY" else 0xF05A5A
    emoji  = "🟢" if sig["signal"] == "BUY" else "🔴"
    action = "買い" if sig["signal"] == "BUY" else "売り"
    jst    = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst).strftime("%Y/%m/%d %H:%M JST")

    fields = [
        {"name": "シグナル",   "value": f"{emoji} **{sig['signal']}**（{action}）", "inline": True},
        {"name": "信頼度",     "value": f"{sig['confidence']*100:.0f}%（{sig['score']}/3条件）", "inline": True},
        {"name": "RSI",        "value": f"{sig['rsi']:.1f}",                          "inline": True},
        {"name": "エントリー", "value": f"`{sig['entry_price']:.5f}`",                "inline": True},
        {"name": "損切 🔴",    "value": f"`{sig['stop_loss']:.5f}`",                  "inline": True},
        {"name": "利確 🟢",    "value": f"`{sig['take_profit']:.5f}`",                "inline": True},
        {"name": "RR比",       "value": f"{sig['risk_reward']:.1f}",                  "inline": True},
    ]
    embed = {
        "title":     f"🤖 FX AI Trader — {instrument} シグナル",
        "description": f"📅 {now_jst}　｜　ルールベース分析",
        "color":     color,
        "fields":    fields,
        "footer":    {"text": "FX AI Trader / GitHub Actions クラウド通知"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        res = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        return res.status_code in (200, 204)
    except Exception as e:
        print(f"[ERROR] Discord 送信失敗: {e}")
        return False


def send_line(token: str, instrument: str, sig: dict) -> bool:
    direction = "🟢 BUY（買い）" if sig["signal"] == "BUY" else "🔴 SELL（売り）"
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst).strftime("%Y/%m/%d %H:%M JST")

    msg = (
        f"\n【FX AI Trader クラウド通知】\n"
        f"日時: {now_jst}\n"
        f"通貨ペア: {instrument}\n"
        f"シグナル: {direction}\n"
        f"信頼度: {sig['confidence']*100:.0f}% ({sig['score']}/3条件)\n"
        f"RSI: {sig['rsi']:.1f}\n"
        f"エントリー: {sig['entry_price']:.5f}\n"
        f"損切: {sig['stop_loss']:.5f}\n"
        f"利確: {sig['take_profit']:.5f}\n"
        f"RR比: {sig['risk_reward']:.1f}"
    )
    try:
        res = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": msg},
            timeout=10,
        )
        return res.status_code == 200
    except Exception as e:
        print(f"[ERROR] LINE 送信失敗: {e}")
        return False


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    print(f"=== FX クラウドスキャン開始 {now.strftime('%Y/%m/%d %H:%M JST')} ===")

    if not is_market_open():
        print(f"市場クローズ中のためスキップ ({now.strftime('%a %H:%M JST')})")
        return

    discord_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    line_token  = os.environ.get("LINE_NOTIFY_TOKEN",   "").strip()

    if not discord_url and not line_token:
        print("[ERROR] DISCORD_WEBHOOK_URL または LINE_NOTIFY_TOKEN が未設定です")
        print("  → GitHub リポジトリの Settings > Secrets に追加してください")
        sys.exit(1)

    found_any = False
    for w in WATCH_LIST:
        symbol     = w["yf_symbol"]
        instrument = w["instrument"]
        print(f"\nスキャン: {instrument} ({symbol})")

        df = fetch_ohlcv(symbol)
        if df is None or len(df) < 60:
            print(f"  データ不足: スキップ（{len(df) if df is not None else 0}本）")
            continue

        sig = detect_signal(df)
        if sig is None:
            print(f"  → HOLD（シグナルなし）RSI={df['close'].pipe(calc_rsi, RSI_PERIOD).iloc[-1]:.1f}")
            continue

        print(f"  → {sig['signal']} 信頼度:{sig['confidence']*100:.0f}% RSI:{sig['rsi']:.1f}")
        found_any = True

        if discord_url:
            ok = send_discord(discord_url, instrument, sig)
            print(f"     Discord: {'✓ 送信成功' if ok else '✗ 送信失敗'}")

        if line_token:
            ok = send_line(line_token, instrument, sig)
            print(f"     LINE:    {'✓ 送信成功' if ok else '✗ 送信失敗'}")

    if not found_any:
        print("\n全ペア HOLD — 通知なし")

    print("\n=== スキャン完了 ===")


if __name__ == "__main__":
    main()
