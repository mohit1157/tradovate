"""Trading signal generator."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
import structlog

from ..sentiment.aggregator import AggregatedSentiment
from ..sentiment.gemini_analyzer import GeminiAnalyzer, SentimentResult
from .risk_calculator import RiskCalculator, RiskParameters

logger = structlog.get_logger()


@dataclass
class TradingSignal:
    """Final trading signal for NinjaTrader."""
    symbol: str
    action: str  # BUY, SELL, HOLD
    quantity: int
    confidence: float
    sentiment_score: float
    reasoning: str
    timestamp: datetime
    risk_params: Optional[RiskParameters] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "action": self.action,
            "qty": self.quantity,
            "confidence": self.confidence,
            "sentiment_score": self.sentiment_score,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_ninja_response(self) -> dict:
        """Convert to NinjaTrader signal server response format."""
        return {
            "action": self.action,
            "qty": self.quantity,
            "confidence": self.confidence,
        }


class SignalGenerator:
    """
    Generates trading signals by combining:
    - Sentiment analysis
    - Risk parameters
    - Optional technical signals
    - Optional Gemini final decision
    """

    def __init__(
        self,
        risk_calculator: RiskCalculator,
        gemini_analyzer: Optional[GeminiAnalyzer] = None,
        use_gemini_decision: bool = True,
    ):
        self.risk_calculator = risk_calculator
        self.gemini_analyzer = gemini_analyzer
        self.use_gemini_decision = use_gemini_decision and gemini_analyzer is not None

    async def generate(
        self,
        symbol: str,
        aggregated_sentiment: AggregatedSentiment,
        technical_signal: Optional[int] = None,
        current_price: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> TradingSignal:
        """
        Generate trading signal from aggregated sentiment and optional technicals.

        Args:
            symbol: Trading symbol
            aggregated_sentiment: Aggregated sentiment from all sources
            technical_signal: Optional technical indicator signal (-1, 0, +1)
            current_price: Optional current market price
            volatility: Optional current volatility (ATR)

        Returns:
            TradingSignal ready for execution
        """
        # Get risk parameters
        risk_params = self.risk_calculator.calculate(
            symbol=symbol,
            confidence=aggregated_sentiment.confidence,
            volatility=volatility,
            current_price=current_price,
        )

        if not risk_params.can_trade:
            return TradingSignal(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                confidence=0.0,
                sentiment_score=aggregated_sentiment.composite_score,
                reasoning=risk_params.reason,
                timestamp=datetime.utcnow(),
                risk_params=risk_params,
            )

        # Determine base action from sentiment
        sentiment_action = aggregated_sentiment.action
        sentiment_confidence = aggregated_sentiment.confidence

        # Combine with technical signal if available
        if technical_signal is not None:
            final_action, final_confidence = self._combine_signals(
                sentiment_action=sentiment_action,
                sentiment_confidence=sentiment_confidence,
                sentiment_score=aggregated_sentiment.composite_score,
                technical_signal=technical_signal,
            )
        else:
            final_action = sentiment_action
            final_confidence = sentiment_confidence

        # Use Gemini for final decision if enabled
        if self.use_gemini_decision and self.gemini_analyzer:
            try:
                # Create a sentiment result for the decision
                sentiment_result = SentimentResult(
                    sentiment_score=aggregated_sentiment.composite_score,
                    confidence=sentiment_confidence,
                    action=sentiment_action,
                    reasoning=f"Themes: {', '.join(aggregated_sentiment.themes)}",
                    key_themes=aggregated_sentiment.themes,
                    urgency="MEDIUM",
                    market_impact="NEUTRAL",
                    timestamp=datetime.utcnow(),
                )

                gemini_decision = await self.gemini_analyzer.generate_trading_decision(
                    sentiment_result=sentiment_result,
                    technical_signal=technical_signal,
                    market_regime=None,  # Could be added later
                )

                final_action = gemini_decision.get("action", final_action)
                final_confidence = gemini_decision.get("confidence", final_confidence)
                reasoning = gemini_decision.get("reasoning", "Gemini decision")

            except Exception as e:
                logger.error("Gemini decision failed, using rule-based", error=str(e))
                reasoning = f"Sentiment: {aggregated_sentiment.composite_score:.2f}"
        else:
            reasoning = f"Sentiment: {aggregated_sentiment.composite_score:.2f}"
            if technical_signal is not None:
                reasoning += f", Technical: {technical_signal}"

        # Calculate final quantity based on confidence and risk
        if final_action == "HOLD":
            final_quantity = 0
        else:
            final_quantity = min(
                risk_params.position_size,
                self.risk_calculator.max_position_size,
            )

        return TradingSignal(
            symbol=symbol,
            action=final_action,
            quantity=final_quantity,
            confidence=final_confidence,
            sentiment_score=aggregated_sentiment.composite_score,
            reasoning=reasoning,
            timestamp=datetime.utcnow(),
            risk_params=risk_params,
        )

    def _combine_signals(
        self,
        sentiment_action: str,
        sentiment_confidence: float,
        sentiment_score: float,
        technical_signal: int,
    ) -> tuple[str, float]:
        """
        Combine sentiment and technical signals.

        Args:
            sentiment_action: Action from sentiment (BUY/SELL/HOLD)
            sentiment_confidence: Confidence from sentiment
            sentiment_score: Raw sentiment score (-1 to +1)
            technical_signal: Technical signal (-1, 0, +1)

        Returns:
            Tuple of (action, confidence)
        """
        # Convert actions to numeric
        action_map = {"BUY": 1, "SELL": -1, "HOLD": 0}
        reverse_map = {1: "BUY", -1: "SELL", 0: "HOLD"}

        sentiment_numeric = action_map.get(sentiment_action, 0)

        # Check for agreement
        if sentiment_numeric == technical_signal:
            # Signals agree - boost confidence
            combined_confidence = min(1.0, sentiment_confidence * 1.2)
            return sentiment_action, combined_confidence

        elif sentiment_numeric == -technical_signal:
            # Signals disagree completely - reduce confidence significantly
            # In this case, prefer HOLD unless one signal is very strong
            if abs(sentiment_score) > 0.6 and sentiment_confidence > 0.7:
                # Sentiment is strong, but reduce confidence
                return sentiment_action, sentiment_confidence * 0.6
            else:
                return "HOLD", 0.3

        else:
            # One signal is neutral
            if technical_signal == 0:
                # Technical is neutral, use sentiment
                return sentiment_action, sentiment_confidence * 0.9
            else:
                # Sentiment is neutral, use technical with reduced confidence
                return reverse_map[technical_signal], 0.5

    def generate_hold_signal(self, symbol: str, reason: str = "No signal") -> TradingSignal:
        """Generate a HOLD signal."""
        return TradingSignal(
            symbol=symbol,
            action="HOLD",
            quantity=0,
            confidence=0.0,
            sentiment_score=0.0,
            reasoning=reason,
            timestamp=datetime.utcnow(),
        )
