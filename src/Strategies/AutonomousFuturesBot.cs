#region Using declarations
using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using NinjaTrader.Cbi;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.NinjaScript.Indicators;
#endregion

// NOTE:
// This is a *starter* autonomous futures strategy for NinjaTrader 8 (NinjaScript).
// It supports two modes:
//   1) Pure rule-based (fast to test): EMA crossover + ATR-based bracket management.
//   2) Optional "External Signal" mode: pull a JSON decision from your local service
//      (where you can run Gemini/news/social sentiment logic) and convert it to trades.
//
// Put this file in: Documents\NinjaTrader 8\bin\Custom\Strategies
// Then compile in NinjaScript Editor.

namespace NinjaTrader.NinjaScript.Strategies
{
    public class AutonomousFuturesBot : Strategy
    {
        // -------- Parameters (configurable in the UI) --------
        [NinjaScriptProperty]
        [Display(Name="Use External Signals", Order=1, GroupName="01 - Mode")]
        public bool UseExternalSignals { get; set; }

        [NinjaScriptProperty]
        [Display(Name="External Signal URL", Order=2, GroupName="01 - Mode")]
        public string ExternalSignalUrl { get; set; } = "http://127.0.0.1:8787/signal?symbol={SYMBOL}";

        [NinjaScriptProperty]
        [Display(Name="External API Key (optional)", Order=3, GroupName="01 - Mode")]
        public string ExternalApiKey { get; set; } = "";

        [NinjaScriptProperty]
        [Display(Name="Fast EMA", Order=1, GroupName="02 - Rule Strategy")]
        public int FastEma { get; set; } = 9;

        [NinjaScriptProperty]
        [Display(Name="Slow EMA", Order=2, GroupName="02 - Rule Strategy")]
        public int SlowEma { get; set; } = 21;

        [NinjaScriptProperty]
        [Display(Name="ATR Period", Order=1, GroupName="03 - Risk")]
        public int AtrPeriod { get; set; } = 14;

        [NinjaScriptProperty]
        [Display(Name="Stop (ATR x)", Order=2, GroupName="03 - Risk")]
        public double StopAtrMult { get; set; } = 1.5;

        [NinjaScriptProperty]
        [Display(Name="Target (ATR x)", Order=3, GroupName="03 - Risk")]
        public double TargetAtrMult { get; set; } = 2.0;

        [NinjaScriptProperty]
        [Display(Name="Max Contracts", Order=4, GroupName="03 - Risk")]
        public int MaxContracts { get; set; } = 1;

        [NinjaScriptProperty]
        [Display(Name="Cooldown (seconds)", Order=5, GroupName="03 - Risk")]
        public int CooldownSeconds { get; set; } = 30;

        // -------- Internal fields --------
        private EMA emaFast;
        private EMA emaSlow;
        private ATR atr;

        private DateTime lastTradeTime = Core.Globals.MinDate;
        private readonly object decisionLock = new object();

        // External decision state (set by background poller)
        private volatile int externalAction = 0;   // -1=SELL, 0=HOLD, +1=BUY
        private volatile int externalQty = 1;
        private volatile double externalConfidence = 0.0;

        private CancellationTokenSource cts;
        private Task pollerTask;
        private static readonly HttpClient http = new HttpClient();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "AutonomousFuturesBot";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsInstantiatedOnEachOptimizationIteration = false;

                UseExternalSignals = false;
            }
            else if (State == State.DataLoaded)
            {
                emaFast = EMA(FastEma);
                emaSlow = EMA(SlowEma);
                atr = ATR(AtrPeriod);

                AddChartIndicator(emaFast);
                AddChartIndicator(emaSlow);
            }
            else if (State == State.Realtime)
            {
                // Start background poller when strategy goes realtime
                if (UseExternalSignals)
                    StartExternalPoller();
            }
            else if (State == State.Terminated)
            {
                StopExternalPoller();
            }
        }

        private void StartExternalPoller()
        {
            try
            {
                cts = new CancellationTokenSource();

                // Avoid "async in OnBarUpdate": poll in background, store atomic decision
                pollerTask = Task.Run(async () =>
                {
                    while (!cts.IsCancellationRequested)
                    {
                        try
                        {
                            string url = (ExternalSignalUrl ?? "").Replace("{SYMBOL}", Instrument?.FullName ?? Instrument?.MasterInstrument?.Name ?? "UNKNOWN");
                            using (var req = new HttpRequestMessage(HttpMethod.Get, url))
                            {
                                if (!string.IsNullOrWhiteSpace(ExternalApiKey))
                                    req.Headers.Add("X-API-Key", ExternalApiKey);

                                using (var resp = await http.SendAsync(req, cts.Token).ConfigureAwait(false))
                                {
                                    string body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
                                    if (resp.IsSuccessStatusCode)
                                    {
                                        // Expected JSON:
                                        // { "action":"BUY|SELL|HOLD", "qty":1, "confidence":0.0-1.0 }
                                        ParseAndStoreDecision(body);
                                    }
                                }
                            }
                        }
                        catch
                        {
                            // Swallow transient errors; your production bot should log and alert.
                        }

                        await Task.Delay(TimeSpan.FromSeconds(2), cts.Token).ConfigureAwait(false);
                    }
                }, cts.Token);
            }
            catch
            {
                // If poller fails to start, we still let rule-based logic run.
            }
        }

        private void StopExternalPoller()
        {
            try
            {
                if (cts != null)
                {
                    cts.Cancel();
                    cts.Dispose();
                    cts = null;
                }
            }
            catch { }
        }

        private void ParseAndStoreDecision(string json)
        {
            // Super-lightweight parsing (no external deps). Keep it simple.
            // For production, you can reference Newtonsoft.Json in a custom DLL.
            string upper = (json ?? "").ToUpperInvariant();

            int action = 0;
            if (upper.Contains("\"ACTION\"") && upper.Contains("BUY")) action = 1;
            else if (upper.Contains("\"ACTION\"") && upper.Contains("SELL")) action = -1;
            else action = 0;

            int qty = 1;
            double conf = 0.0;

            // naive qty parse: "qty": 2
            try
            {
                var qMatch = System.Text.RegularExpressions.Regex.Match(json, "\"qty\"\\s*:\\s*(\\d+)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                if (qMatch.Success) qty = Math.Max(1, Math.Min(MaxContracts, int.Parse(qMatch.Groups[1].Value)));
            }
            catch { }

            // naive confidence parse: "confidence": 0.73
            try
            {
                var cMatch = System.Text.RegularExpressions.Regex.Match(json, "\"confidence\"\\s*:\\s*([0-9]*\\.?[0-9]+)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                if (cMatch.Success) conf = Math.Max(0.0, Math.Min(1.0, double.Parse(cMatch.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture)));
            }
            catch { }

            externalAction = action;
            externalQty = qty;
            externalConfidence = conf;
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < Math.Max(SlowEma, AtrPeriod) + 5)
                return;

            // Cooldown to avoid overtrading
            if ((Time[0] - lastTradeTime).TotalSeconds < CooldownSeconds)
                return;

            // Determine signal source
            int action = 0; // -1 sell, +1 buy, 0 hold

            if (UseExternalSignals)
            {
                // Require minimum confidence if you want (example: 0.55)
                if (externalConfidence >= 0.55)
                    action = externalAction;
                else
                    action = 0;
            }
            else
            {
                // Rule-based: EMA crossover
                bool crossUp = CrossAbove(emaFast, emaSlow, 1);
                bool crossDown = CrossBelow(emaFast, emaSlow, 1);

                if (crossUp) action = 1;
                else if (crossDown) action = -1;
            }

            // Risk-based bracket distances
            double atrVal = atr[0];
            if (atrVal <= 0) return;

            int qtyToUse = UseExternalSignals ? Math.Max(1, Math.Min(MaxContracts, externalQty)) : MaxContracts;

            // Flat -> enter
            if (Position.MarketPosition == MarketPosition.Flat)
            {
                if (action == 1)
                {
                    SetStopLoss(CalculationMode.Price, Close[0] - (StopAtrMult * atrVal));
                    SetProfitTarget(CalculationMode.Price, Close[0] + (TargetAtrMult * atrVal));
                    EnterLong(qtyToUse, "LongEntry");
                    lastTradeTime = Time[0];
                }
                else if (action == -1)
                {
                    SetStopLoss(CalculationMode.Price, Close[0] + (StopAtrMult * atrVal));
                    SetProfitTarget(CalculationMode.Price, Close[0] - (TargetAtrMult * atrVal));
                    EnterShort(qtyToUse, "ShortEntry");
                    lastTradeTime = Time[0];
                }
            }
            else
            {
                // Optional: if external says reverse, flatten
                if (UseExternalSignals)
                {
                    if (Position.MarketPosition == MarketPosition.Long && action == -1)
                    {
                        ExitLong("ExitLongReverse", "LongEntry");
                        lastTradeTime = Time[0];
                    }
                    if (Position.MarketPosition == MarketPosition.Short && action == 1)
                    {
                        ExitShort("ExitShortReverse", "ShortEntry");
                        lastTradeTime = Time[0];
                    }
                }
            }
        }
    }
}
