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

// ============================================================================
// AUTONOMOUS FUTURES TRADING BOT FOR NINJATRADER 8
// ============================================================================
// A comprehensive autonomous trading strategy that combines:
//   1) Technical Analysis: EMA crossover with ATR-based risk management
//   2) Sentiment Analysis: Integrates with external AI service (Gemini)
//   3) Advanced Risk Controls: Daily loss limits, trade limits, kill switch
//
// Installation:
//   Put this file in: Documents\NinjaTrader 8\bin\Custom\Strategies
//   Then compile in NinjaScript Editor (F5)
//
// External Signal Server:
//   Run the Python signal server: python -m src.server.signal_server
//   Server provides AI-powered sentiment signals from Twitter, Reddit, News
// ============================================================================

namespace NinjaTrader.NinjaScript.Strategies
{
    public class AutonomousFuturesBot : Strategy
    {
        #region Parameters

        // -------- Mode Configuration --------
        [NinjaScriptProperty]
        [Display(Name="Use External Signals", Description="Enable AI-powered sentiment signals", Order=1, GroupName="01 - Mode")]
        public bool UseExternalSignals { get; set; }

        [NinjaScriptProperty]
        [Display(Name="External Signal URL", Description="URL of signal server with {SYMBOL} placeholder", Order=2, GroupName="01 - Mode")]
        public string ExternalSignalUrl { get; set; } = "http://127.0.0.1:8787/signal?symbol={SYMBOL}";

        [NinjaScriptProperty]
        [Display(Name="External API Key (optional)", Order=3, GroupName="01 - Mode")]
        public string ExternalApiKey { get; set; } = "";

        [NinjaScriptProperty]
        [Display(Name="Minimum Confidence", Description="Minimum confidence to execute external signal", Order=4, GroupName="01 - Mode")]
        public double MinConfidence { get; set; } = 0.55;

        // -------- Technical Strategy --------
        [NinjaScriptProperty]
        [Display(Name="Fast EMA Period", Order=1, GroupName="02 - Technical Strategy")]
        public int FastEma { get; set; } = 9;

        [NinjaScriptProperty]
        [Display(Name="Slow EMA Period", Order=2, GroupName="02 - Technical Strategy")]
        public int SlowEma { get; set; } = 21;

        [NinjaScriptProperty]
        [Display(Name="ATR Period", Order=3, GroupName="02 - Technical Strategy")]
        public int AtrPeriod { get; set; } = 14;

        // -------- Risk Management --------
        [NinjaScriptProperty]
        [Display(Name="Stop Loss (ATR multiplier)", Order=1, GroupName="03 - Risk Management")]
        public double StopAtrMult { get; set; } = 1.5;

        [NinjaScriptProperty]
        [Display(Name="Profit Target (ATR multiplier)", Order=2, GroupName="03 - Risk Management")]
        public double TargetAtrMult { get; set; } = 2.0;

        [NinjaScriptProperty]
        [Display(Name="Max Contracts Per Trade", Order=3, GroupName="03 - Risk Management")]
        public int MaxContracts { get; set; } = 1;

        [NinjaScriptProperty]
        [Display(Name="Cooldown Between Trades (seconds)", Order=4, GroupName="03 - Risk Management")]
        public int CooldownSeconds { get; set; } = 30;

        // -------- Advanced Risk Controls --------
        [NinjaScriptProperty]
        [Display(Name="Enable Daily Loss Limit", Order=1, GroupName="04 - Advanced Risk")]
        public bool EnableDailyLossLimit { get; set; } = true;

        [NinjaScriptProperty]
        [Display(Name="Max Daily Loss ($)", Description="Stop trading when daily loss exceeds this", Order=2, GroupName="04 - Advanced Risk")]
        public double MaxDailyLoss { get; set; } = 500.0;

        [NinjaScriptProperty]
        [Display(Name="Max Trades Per Day", Order=3, GroupName="04 - Advanced Risk")]
        public int MaxTradesPerDay { get; set; } = 10;

        [NinjaScriptProperty]
        [Display(Name="Enable Trailing Stop", Order=4, GroupName="04 - Advanced Risk")]
        public bool EnableTrailingStop { get; set; } = false;

        [NinjaScriptProperty]
        [Display(Name="Trailing Stop (ATR multiplier)", Order=5, GroupName="04 - Advanced Risk")]
        public double TrailingStopAtrMult { get; set; } = 1.0;

        #endregion

        #region Internal Fields

        // Indicators
        private EMA emaFast;
        private EMA emaSlow;
        private ATR atr;

        // Trade tracking
        private DateTime lastTradeTime = Core.Globals.MinDate;
        private DateTime currentTradingDay = DateTime.MinValue;
        private int tradesThisDay = 0;
        private double dailyPnL = 0.0;
        private bool isKillSwitchActive = false;

        // External signal state (set by background poller)
        private volatile int externalAction = 0;   // -1=SELL, 0=HOLD, +1=BUY
        private volatile int externalQty = 1;
        private volatile double externalConfidence = 0.0;
        private volatile bool externalServiceHealthy = false;

        // Background poller
        private CancellationTokenSource cts;
        private Task pollerTask;
        private static readonly HttpClient http = new HttpClient() { Timeout = TimeSpan.FromSeconds(10) };

        // Position tracking for P&L
        private double entryPrice = 0;
        private int entryQuantity = 0;

        #endregion

        #region Strategy Lifecycle

        protected override void OnStateChange()
        {
            switch (State)
            {
                case State.SetDefaults:
                    InitializeDefaults();
                    break;

                case State.DataLoaded:
                    InitializeIndicators();
                    break;

                case State.Realtime:
                    OnRealtimeStart();
                    break;

                case State.Terminated:
                    OnTerminated();
                    break;
            }
        }

        private void InitializeDefaults()
        {
            Name = "AutonomousFuturesBot";
            Description = "AI-powered autonomous futures trading with sentiment analysis";
            Calculate = Calculate.OnBarClose;
            EntriesPerDirection = 1;
            EntryHandling = EntryHandling.AllEntries;
            IsExitOnSessionCloseStrategy = true;
            ExitOnSessionCloseSeconds = 30;
            IsInstantiatedOnEachOptimizationIteration = false;
            UseExternalSignals = false;
        }

        private void InitializeIndicators()
        {
            emaFast = EMA(FastEma);
            emaSlow = EMA(SlowEma);
            atr = ATR(AtrPeriod);

            AddChartIndicator(emaFast);
            AddChartIndicator(emaSlow);
        }

        private void OnRealtimeStart()
        {
            // Reset daily counters
            ResetDailyCounters();

            // Start background poller for external signals
            if (UseExternalSignals)
            {
                StartExternalPoller();
                CheckServiceHealth();
            }

            Log("Strategy started in realtime mode", LogLevel.Information);
        }

        private void OnTerminated()
        {
            StopExternalPoller();
            Log("Strategy terminated", LogLevel.Information);
        }

        #endregion

        #region Main Trading Logic

        protected override void OnBarUpdate()
        {
            // Warmup period
            if (CurrentBar < Math.Max(SlowEma, AtrPeriod) + 5)
                return;

            // Check if new trading day
            CheckNewTradingDay();

            // Check kill switch
            if (isKillSwitchActive)
            {
                if (Position.MarketPosition != MarketPosition.Flat)
                {
                    FlattenPosition("Kill switch active");
                }
                return;
            }

            // Check daily limits
            if (!CheckDailyLimits())
                return;

            // Check cooldown
            if ((Time[0] - lastTradeTime).TotalSeconds < CooldownSeconds)
                return;

            // Get trading signal
            int action = GetTradingSignal();
            if (action == 0)
                return;

            // Get ATR for position sizing and stops
            double atrVal = atr[0];
            if (atrVal <= 0)
                return;

            // Execute trading logic
            ExecuteTrade(action, atrVal);
        }

        private int GetTradingSignal()
        {
            if (UseExternalSignals)
            {
                return GetExternalSignal();
            }
            else
            {
                return GetTechnicalSignal();
            }
        }

        private int GetExternalSignal()
        {
            // Check service health
            if (!externalServiceHealthy)
            {
                // Fallback to technical signals if service is down
                return GetTechnicalSignal();
            }

            // Check minimum confidence threshold
            if (externalConfidence >= MinConfidence)
            {
                return externalAction;
            }

            return 0; // HOLD
        }

        private int GetTechnicalSignal()
        {
            // EMA crossover strategy
            bool crossUp = CrossAbove(emaFast, emaSlow, 1);
            bool crossDown = CrossBelow(emaFast, emaSlow, 1);

            if (crossUp) return 1;   // BUY
            if (crossDown) return -1; // SELL
            return 0; // HOLD
        }

        private void ExecuteTrade(int action, double atrVal)
        {
            int qtyToUse = UseExternalSignals
                ? Math.Max(1, Math.Min(MaxContracts, externalQty))
                : MaxContracts;

            if (Position.MarketPosition == MarketPosition.Flat)
            {
                // Enter new position
                if (action == 1)
                {
                    EnterLongPosition(qtyToUse, atrVal);
                }
                else if (action == -1)
                {
                    EnterShortPosition(qtyToUse, atrVal);
                }
            }
            else
            {
                // Handle position reversal (only in external signal mode)
                if (UseExternalSignals)
                {
                    HandlePositionReversal(action);
                }
            }
        }

        private void EnterLongPosition(int qty, double atrVal)
        {
            double stopPrice = Close[0] - (StopAtrMult * atrVal);
            double targetPrice = Close[0] + (TargetAtrMult * atrVal);

            if (EnableTrailingStop)
            {
                SetTrailStop(CalculationMode.Price, TrailingStopAtrMult * atrVal);
            }
            else
            {
                SetStopLoss(CalculationMode.Price, stopPrice);
            }

            SetProfitTarget(CalculationMode.Price, targetPrice);
            EnterLong(qty, "LongEntry");

            entryPrice = Close[0];
            entryQuantity = qty;
            lastTradeTime = Time[0];
            tradesThisDay++;

            Log($"LONG Entry: Qty={qty}, Stop={stopPrice:F2}, Target={targetPrice:F2}, Confidence={externalConfidence:F2}", LogLevel.Information);
        }

        private void EnterShortPosition(int qty, double atrVal)
        {
            double stopPrice = Close[0] + (StopAtrMult * atrVal);
            double targetPrice = Close[0] - (TargetAtrMult * atrVal);

            if (EnableTrailingStop)
            {
                SetTrailStop(CalculationMode.Price, TrailingStopAtrMult * atrVal);
            }
            else
            {
                SetStopLoss(CalculationMode.Price, stopPrice);
            }

            SetProfitTarget(CalculationMode.Price, targetPrice);
            EnterShort(qty, "ShortEntry");

            entryPrice = Close[0];
            entryQuantity = qty;
            lastTradeTime = Time[0];
            tradesThisDay++;

            Log($"SHORT Entry: Qty={qty}, Stop={stopPrice:F2}, Target={targetPrice:F2}, Confidence={externalConfidence:F2}", LogLevel.Information);
        }

        private void HandlePositionReversal(int action)
        {
            if (Position.MarketPosition == MarketPosition.Long && action == -1)
            {
                ExitLong("ExitLongReverse", "LongEntry");
                lastTradeTime = Time[0];
                Log("Exiting long position on reversal signal", LogLevel.Information);
            }
            else if (Position.MarketPosition == MarketPosition.Short && action == 1)
            {
                ExitShort("ExitShortReverse", "ShortEntry");
                lastTradeTime = Time[0];
                Log("Exiting short position on reversal signal", LogLevel.Information);
            }
        }

        private void FlattenPosition(string reason)
        {
            if (Position.MarketPosition == MarketPosition.Long)
            {
                ExitLong($"Exit_{reason}", "LongEntry");
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                ExitShort($"Exit_{reason}", "ShortEntry");
            }
            Log($"Position flattened: {reason}", LogLevel.Warning);
        }

        #endregion

        #region Risk Management

        private void CheckNewTradingDay()
        {
            if (Time[0].Date != currentTradingDay.Date)
            {
                ResetDailyCounters();
            }
        }

        private void ResetDailyCounters()
        {
            currentTradingDay = Time[0].Date;
            tradesThisDay = 0;
            dailyPnL = 0.0;
            isKillSwitchActive = false;
            Log($"Daily counters reset for {currentTradingDay:yyyy-MM-dd}", LogLevel.Information);
        }

        private bool CheckDailyLimits()
        {
            // Check trade count limit
            if (tradesThisDay >= MaxTradesPerDay)
            {
                return false;
            }

            // Check daily loss limit
            if (EnableDailyLossLimit && dailyPnL <= -MaxDailyLoss)
            {
                if (!isKillSwitchActive)
                {
                    ActivateKillSwitch($"Daily loss limit reached: ${Math.Abs(dailyPnL):F2}");
                }
                return false;
            }

            return true;
        }

        private void ActivateKillSwitch(string reason)
        {
            isKillSwitchActive = true;
            Log($"KILL SWITCH ACTIVATED: {reason}", LogLevel.Alert);

            // Notify external server if available
            NotifyKillSwitch(reason);
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            // Track P&L on position close
            if (execution.Order.OrderState == OrderState.Filled)
            {
                if (execution.Order.Name.Contains("Exit") || execution.Order.Name.Contains("Stop") || execution.Order.Name.Contains("Target"))
                {
                    // Calculate P&L
                    double pnl = CalculatePnL(execution, price, quantity);
                    dailyPnL += pnl;

                    Log($"Trade closed: P&L=${pnl:F2}, Daily P&L=${dailyPnL:F2}", LogLevel.Information);

                    // Report to external server
                    ReportTradeToServer(pnl);

                    // Check if kill switch should be activated
                    if (EnableDailyLossLimit && dailyPnL <= -MaxDailyLoss)
                    {
                        ActivateKillSwitch($"Daily loss limit reached: ${Math.Abs(dailyPnL):F2}");
                    }
                }
            }
        }

        private double CalculatePnL(Execution execution, double exitPrice, int quantity)
        {
            if (entryPrice == 0) return 0;

            double pnl;
            if (execution.Order.Name.Contains("Long") || Position.MarketPosition == MarketPosition.Long)
            {
                pnl = (exitPrice - entryPrice) * quantity * Instrument.MasterInstrument.PointValue;
            }
            else
            {
                pnl = (entryPrice - exitPrice) * quantity * Instrument.MasterInstrument.PointValue;
            }

            entryPrice = 0;
            entryQuantity = 0;
            return pnl;
        }

        #endregion

        #region External Signal Server Communication

        private void StartExternalPoller()
        {
            try
            {
                cts = new CancellationTokenSource();

                pollerTask = Task.Run(async () =>
                {
                    while (!cts.IsCancellationRequested)
                    {
                        try
                        {
                            await PollExternalSignal();
                        }
                        catch (Exception ex)
                        {
                            externalServiceHealthy = false;
                            // Log error but continue polling
                        }

                        await Task.Delay(TimeSpan.FromSeconds(2), cts.Token).ConfigureAwait(false);
                    }
                }, cts.Token);

                Log("External signal poller started", LogLevel.Information);
            }
            catch (Exception ex)
            {
                Log($"Failed to start external poller: {ex.Message}", LogLevel.Error);
            }
        }

        private async Task PollExternalSignal()
        {
            string symbolName = Instrument?.MasterInstrument?.Name ?? "UNKNOWN";
            string url = (ExternalSignalUrl ?? "").Replace("{SYMBOL}", symbolName);

            using (var req = new HttpRequestMessage(HttpMethod.Get, url))
            {
                if (!string.IsNullOrWhiteSpace(ExternalApiKey))
                {
                    req.Headers.Add("X-API-Key", ExternalApiKey);
                }

                using (var resp = await http.SendAsync(req, cts.Token).ConfigureAwait(false))
                {
                    if (resp.IsSuccessStatusCode)
                    {
                        string body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
                        ParseAndStoreDecision(body);
                        externalServiceHealthy = true;
                    }
                    else
                    {
                        externalServiceHealthy = false;
                    }
                }
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
            if (string.IsNullOrEmpty(json)) return;

            try
            {
                string upper = json.ToUpperInvariant();

                // Parse action
                int action = 0;
                if (upper.Contains("\"ACTION\""))
                {
                    if (upper.Contains("\"BUY\"")) action = 1;
                    else if (upper.Contains("\"SELL\"")) action = -1;
                }

                // Parse quantity
                int qty = 1;
                var qMatch = System.Text.RegularExpressions.Regex.Match(
                    json, "\"qty\"\\s*:\\s*(\\d+)",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                if (qMatch.Success)
                {
                    qty = Math.Max(1, Math.Min(MaxContracts, int.Parse(qMatch.Groups[1].Value)));
                }

                // Parse confidence
                double conf = 0.0;
                var cMatch = System.Text.RegularExpressions.Regex.Match(
                    json, "\"confidence\"\\s*:\\s*([0-9]*\\.?[0-9]+)",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                if (cMatch.Success)
                {
                    conf = Math.Max(0.0, Math.Min(1.0,
                        double.Parse(cMatch.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture)));
                }

                // Store atomically
                externalAction = action;
                externalQty = qty;
                externalConfidence = conf;
            }
            catch (Exception ex)
            {
                // Log parsing error
            }
        }

        private async void CheckServiceHealth()
        {
            try
            {
                string healthUrl = ExternalSignalUrl.Replace("/signal", "/health").Split('?')[0];
                var response = await http.GetAsync(healthUrl);
                externalServiceHealthy = response.IsSuccessStatusCode;

                if (externalServiceHealthy)
                {
                    Log("External signal service is healthy", LogLevel.Information);
                }
                else
                {
                    Log("External signal service is not responding - using technical fallback", LogLevel.Warning);
                }
            }
            catch
            {
                externalServiceHealthy = false;
                Log("Cannot reach external signal service - using technical fallback", LogLevel.Warning);
            }
        }

        private async void ReportTradeToServer(double pnl)
        {
            if (!UseExternalSignals) return;

            try
            {
                string baseUrl = ExternalSignalUrl.Split('?')[0].Replace("/signal", "");
                string url = $"{baseUrl}/record-trade?pnl={pnl}";
                await http.PostAsync(url, null);
            }
            catch { }
        }

        private async void NotifyKillSwitch(string reason)
        {
            if (!UseExternalSignals) return;

            try
            {
                string baseUrl = ExternalSignalUrl.Split('?')[0].Replace("/signal", "");
                string url = $"{baseUrl}/kill?reason={Uri.EscapeDataString(reason)}";
                await http.PostAsync(url, null);
            }
            catch { }
        }

        #endregion

        #region Logging

        private void Log(string message, LogLevel level)
        {
            string timestamp = DateTime.Now.ToString("HH:mm:ss");
            string prefix = $"[{timestamp}] [{Name}]";

            switch (level)
            {
                case LogLevel.Alert:
                    Print($"{prefix} ALERT: {message}");
                    break;
                case LogLevel.Error:
                    Print($"{prefix} ERROR: {message}");
                    break;
                case LogLevel.Warning:
                    Print($"{prefix} WARN: {message}");
                    break;
                case LogLevel.Information:
                    Print($"{prefix} INFO: {message}");
                    break;
                default:
                    Print($"{prefix} {message}");
                    break;
            }
        }

        private enum LogLevel
        {
            Information,
            Warning,
            Error,
            Alert
        }

        #endregion
    }
}
