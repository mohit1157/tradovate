# NinjaTrader Autonomous Futures Bot (Starter Project)

This zip contains a **starter NinjaTrader 8 NinjaScript strategy** that can run autonomously and (optionally) pull decisions from an external AI/sentiment service.

## What you get

- `AutonomousFuturesBot.cs` (NinjaScript Strategy)
  - Rule-based mode: **EMA crossover** + **ATR-based stop/target**
  - Optional external-signal mode: polls a local URL returning JSON (where you can run Gemini/news/social sentiment)
- `signal_server.py` (tiny local example server you can replace with your real Gemini pipeline)

---

## 1) Install/prepare NinjaTrader 8

1. Install **NinjaTrader 8 Desktop**.
2. Use **Sim** (replay/sim account) first.

---

## 2) Add the strategy to NinjaTrader

### Option A — Copy the `.cs` file manually (fastest)
Copy:

`src/Strategies/AutonomousFuturesBot.cs`

to your NinjaTrader custom strategies folder:

`Documents\NinjaTrader 8\bin\Custom\Strategies`  citeturn0search2turn0search11

Then open NinjaTrader:
- Go to **New > NinjaScript Editor**
- Press **F5** (Compile)

### Option B — Import a NinjaScript Add-On package
NinjaTrader supports importing add-ons via:

**Control Center > Tools > Import > NinjaScript Add-On** citeturn0search12

(For vendor-style distribution, NinjaTrader also documents how to create a distribution/export package.) citeturn0search4

---

## 3) Enable the strategy (autonomous execution)

You can enable strategies from the **Control Center > Strategies tab**:
- Right-click → **New Strategy**
- Select `AutonomousFuturesBot`
- Set instrument/timeframe
- Check **Enable** to turn on automation citeturn0search10turn0search13

NinjaTrader also documents enabling automated strategies directly on a chart. citeturn0search19

---

## 4) How “autonomous” logic works in this starter

### Rule-based mode (default)
- Enter long when fast EMA crosses above slow EMA
- Enter short when fast EMA crosses below slow EMA
- Brackets:
  - Stop = `StopAtrMult * ATR`
  - Target = `TargetAtrMult * ATR`

### External-signal mode (recommended for Gemini/sentiment)
Set:
- **Use External Signals** = `true`
- **External Signal URL** = `http://127.0.0.1:8787/signal?symbol={SYMBOL}`

The strategy runs a **background poller** (every ~2 seconds), stores the last decision, and `OnBarUpdate()` uses it when confidence ≥ 0.55.

**Expected JSON:**
```json
{ "action": "BUY", "qty": 1, "confidence": 0.78 }
```

---

## 5) Run the example external signal server

From this project folder:

```bash
cd src/ExternalSignalService
python signal_server.py
```

Now NinjaTrader will be able to call:

`http://127.0.0.1:8787/signal?symbol={SYMBOL}`

Replace the `compute_signal()` function with your real pipeline.

---

## 6) Best ways to integrate NinjaTrader with an autonomous “brain”

### A) In-platform (pure NinjaScript)
Your entire strategy lives inside NinjaTrader.
- ✅ Simplest deployment
- ✅ Fast execution
- ❌ Harder to integrate large ML stacks/LLMs

### B) Hybrid (recommended): NinjaTrader executes, external service decides
- NinjaScript handles **orders, brackets, safety**
- Your external service handles:
  - news/social ingest
  - Gemini sentiment
  - feature engineering
  - final decision output

This project implements this hybrid pattern.

### C) External application controlling NinjaTrader through API
NinjaTrader provides a developer guide for using an API DLL (`NinjaTrader.Client.dll`) to connect an external application with NinjaTrader. citeturn0search1

Use this when you want deeper integration than “poll a URL”, but it’s more complex than the hybrid approach.

### D) NinjaTrader “Trader APIs” (REST)
NinjaTrader also offers REST APIs intended for client applications to connect to NinjaTrader’s infrastructure. citeturn0search9  
(Useful if you want to automate through their broader ecosystem rather than only desktop-hosted logic.)

---

## Safety notes (important)
- Start in **Sim**.
- Add hard limits: max daily loss, max trades/hour, max position size, kill switch.
- Watch out for:
  - connection drops
  - session breaks / illiquid periods
  - order rejections

---

## Files

- `src/Strategies/AutonomousFuturesBot.cs`
- `src/ExternalSignalService/signal_server.py`
- `docs/EXTERNAL_SIGNALS.md`

---

## Next upgrade ideas (if you want “v2”)
- OCO brackets with dynamic trailing stop
- persistent state + trade journal (SQLite/Postgres)
- live telemetry dashboard
- reconnect-safe order reconciliation
- richer JSON schema: regime, volatility, stop/target suggestions, invalidate price
