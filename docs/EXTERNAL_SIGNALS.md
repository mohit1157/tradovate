# External Signal Service (Optional)

The NinjaScript strategy can optionally pull an "action" from an external service.

Expected JSON response:

```json
{
  "action": "BUY",
  "qty": 1,
  "confidence": 0.78
}
```

Suggested approach:
- Run a local service (Python/Node) that:
  - collects news/social posts
  - runs Gemini (or other model) for sentiment + classification
  - produces a *single* decision for the instrument and timeframe you're trading

Then point the strategy parameter **External Signal URL** to your service, e.g.:

`http://127.0.0.1:8787/signal?symbol={SYMBOL}`

This project includes a tiny Python example server in `/src/ExternalSignalService`.
