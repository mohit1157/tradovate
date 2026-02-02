"""Gemini AI-powered sentiment analyzer."""

import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import json
import structlog

logger = structlog.get_logger()


@dataclass
class SentimentResult:
    """Result of sentiment analysis."""
    sentiment_score: float  # -1.0 (bearish) to +1.0 (bullish)
    confidence: float  # 0.0 to 1.0
    action: str  # BUY, SELL, HOLD
    reasoning: str
    key_themes: List[str]
    urgency: str  # LOW, MEDIUM, HIGH
    market_impact: str  # POSITIVE, NEGATIVE, NEUTRAL
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "action": self.action,
            "reasoning": self.reasoning,
            "key_themes": self.key_themes,
            "urgency": self.urgency,
            "market_impact": self.market_impact,
            "timestamp": self.timestamp.isoformat(),
        }


class GeminiAnalyzer:
    """
    Sentiment analyzer using Google Gemini AI.

    Uses Gemini Pro for advanced financial sentiment analysis
    with context-aware prompting.
    """

    # System prompt for financial sentiment analysis
    SYSTEM_PROMPT = """You are an expert financial sentiment analyzer specializing in futures markets.
Your task is to analyze text data from social media and news to determine market sentiment.

You must output ONLY a valid JSON object with the following structure:
{
    "sentiment_score": <float between -1.0 and 1.0>,
    "confidence": <float between 0.0 and 1.0>,
    "action": "<BUY|SELL|HOLD>",
    "reasoning": "<brief explanation>",
    "key_themes": ["<theme1>", "<theme2>"],
    "urgency": "<LOW|MEDIUM|HIGH>",
    "market_impact": "<POSITIVE|NEGATIVE|NEUTRAL>"
}

Guidelines:
- sentiment_score: -1.0 = extremely bearish, 0 = neutral, +1.0 = extremely bullish
- confidence: How confident you are in the analysis (consider data quality, consistency)
- action: BUY if sentiment_score > 0.3 and confidence > 0.6
         SELL if sentiment_score < -0.3 and confidence > 0.6
         HOLD otherwise
- Consider the source reliability (news > verified accounts > general social media)
- Look for consensus across multiple data points
- Be skeptical of extreme sentiment without substantiation
- Consider contrarian indicators (extreme bullishness can be bearish)

IMPORTANT: Output ONLY the JSON object, no other text."""

    def __init__(self):
        self._model = None
        self._enabled = False

    async def initialize(self) -> bool:
        """Initialize Gemini client."""
        try:
            import google.generativeai as genai
            from config.settings import settings

            if not settings.gemini_enabled:
                logger.warning("Gemini analyzer disabled - no API key configured")
                return False

            genai.configure(api_key=settings.gemini_api_key)

            # Use Gemini Pro for best results
            self._model = genai.GenerativeModel(
                model_name="gemini-pro",
                generation_config={
                    "temperature": 0.3,  # Lower for more consistent analysis
                    "top_p": 0.8,
                    "top_k": 40,
                    "max_output_tokens": 500,
                },
            )

            self._enabled = True
            logger.info("Gemini analyzer initialized successfully")
            return True

        except ImportError:
            logger.warning("google-generativeai not installed")
            return False
        except Exception as e:
            logger.error("Failed to initialize Gemini analyzer", error=str(e))
            return False

    async def analyze(
        self,
        texts: List[str],
        symbol: str,
        sources: Optional[List[str]] = None,
    ) -> SentimentResult:
        """
        Analyze sentiment of multiple texts.

        Args:
            texts: List of text content to analyze
            symbol: Trading symbol for context
            sources: Optional list of source labels for each text

        Returns:
            SentimentResult with analysis
        """
        if not self._enabled or not self._model:
            return self._default_result()

        if not texts:
            return self._default_result()

        try:
            # Build analysis prompt
            prompt = self._build_prompt(texts, symbol, sources)

            # Call Gemini
            response = await asyncio.to_thread(
                self._model.generate_content, prompt
            )

            # Parse response
            result = self._parse_response(response.text)
            return result

        except Exception as e:
            logger.error("Gemini analysis failed", error=str(e))
            return self._default_result()

    async def analyze_single(self, text: str, symbol: str, source: str = "unknown") -> SentimentResult:
        """Analyze a single piece of text."""
        return await self.analyze([text], symbol, [source])

    def _build_prompt(
        self,
        texts: List[str],
        symbol: str,
        sources: Optional[List[str]] = None,
    ) -> str:
        """Build the analysis prompt."""
        from config.settings import SYMBOL_MAPPINGS

        # Get symbol info
        symbol_info = SYMBOL_MAPPINGS.get(symbol, {"name": symbol})
        symbol_name = symbol_info.get("name", symbol)

        # Build data section
        data_section = f"## Market Data for {symbol_name} ({symbol})\n\n"

        for i, text in enumerate(texts[:20]):  # Limit to 20 items
            source = sources[i] if sources and i < len(sources) else "unknown"
            # Truncate long texts
            truncated = text[:500] + "..." if len(text) > 500 else text
            data_section += f"### Source: {source}\n{truncated}\n\n"

        # Full prompt
        prompt = f"""{self.SYSTEM_PROMPT}

{data_section}

Analyze the above data and provide your sentiment assessment for {symbol_name} futures."""

        return prompt

    def _parse_response(self, response_text: str) -> SentimentResult:
        """Parse Gemini's JSON response."""
        try:
            # Try to extract JSON from response
            # Sometimes Gemini adds markdown code blocks
            json_text = response_text.strip()
            if json_text.startswith("```"):
                # Extract from code block
                lines = json_text.split("\n")
                json_lines = []
                in_json = False
                for line in lines:
                    if line.startswith("```") and not in_json:
                        in_json = True
                        continue
                    elif line.startswith("```") and in_json:
                        break
                    elif in_json:
                        json_lines.append(line)
                json_text = "\n".join(json_lines)

            data = json.loads(json_text)

            return SentimentResult(
                sentiment_score=float(data.get("sentiment_score", 0)),
                confidence=float(data.get("confidence", 0.5)),
                action=data.get("action", "HOLD").upper(),
                reasoning=data.get("reasoning", "No reasoning provided"),
                key_themes=data.get("key_themes", []),
                urgency=data.get("urgency", "LOW").upper(),
                market_impact=data.get("market_impact", "NEUTRAL").upper(),
                timestamp=datetime.utcnow(),
            )

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse Gemini response as JSON", error=str(e))
            return self._default_result()

    def _default_result(self) -> SentimentResult:
        """Return a neutral/hold result."""
        return SentimentResult(
            sentiment_score=0.0,
            confidence=0.0,
            action="HOLD",
            reasoning="Unable to analyze - using default",
            key_themes=[],
            urgency="LOW",
            market_impact="NEUTRAL",
            timestamp=datetime.utcnow(),
        )

    async def generate_trading_decision(
        self,
        sentiment_result: SentimentResult,
        technical_signal: Optional[int] = None,
        market_regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate final trading decision combining sentiment with other signals.

        Args:
            sentiment_result: Result from sentiment analysis
            technical_signal: Optional technical signal (-1, 0, +1)
            market_regime: Optional market regime (trending, ranging, volatile)

        Returns:
            Trading decision dictionary
        """
        if not self._enabled or not self._model:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": "Analyzer not available",
            }

        try:
            prompt = f"""As a trading decision system, combine the following signals to make a final decision.

## Sentiment Analysis
- Score: {sentiment_result.sentiment_score:.2f}
- Confidence: {sentiment_result.confidence:.2f}
- Suggested Action: {sentiment_result.action}
- Key Themes: {', '.join(sentiment_result.key_themes)}
- Urgency: {sentiment_result.urgency}
- Reasoning: {sentiment_result.reasoning}

## Technical Signal
- Signal: {technical_signal if technical_signal is not None else 'Not available'} (1=bullish, -1=bearish, 0=neutral)

## Market Regime
- Current Regime: {market_regime or 'Unknown'}

Based on all available information, output a JSON decision:
{{
    "action": "<BUY|SELL|HOLD>",
    "quantity": <1-5>,
    "confidence": <0.0-1.0>,
    "reasoning": "<brief explanation>"
}}

Rules:
- Require agreement between sentiment and technicals for high confidence trades
- In volatile regimes, reduce position sizes and require higher confidence
- In trending regimes, align with the trend
- HOLD when signals conflict or confidence is low

Output ONLY the JSON object."""

            response = await asyncio.to_thread(
                self._model.generate_content, prompt
            )

            # Parse response
            json_text = response.text.strip()
            if json_text.startswith("```"):
                lines = json_text.split("\n")
                json_lines = [l for l in lines if not l.startswith("```")]
                json_text = "\n".join(json_lines)

            return json.loads(json_text)

        except Exception as e:
            logger.error("Decision generation failed", error=str(e))
            return {
                "action": "HOLD",
                "quantity": 1,
                "confidence": 0.0,
                "reasoning": f"Error generating decision: {str(e)}",
            }
