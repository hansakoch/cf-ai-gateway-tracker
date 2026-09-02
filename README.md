# CF AI Gateway Tracker

Unified AI usage tracking through Cloudflare AI Gateway. One applet to rule them all — Xiaomi MiMo, OpenAI, Anthropic, Grok, Workers AI, and any BYOK provider.

## What it does

Routes all your AI API calls through Cloudflare AI Gateway and displays usage analytics in your Omarchy panel:

- **Daily/monthly token usage** across all providers
- **Per-provider breakdown** (who's eating your credits)
- **Cost tracking** in USD
- **7-day usage chart**
- **Run-out date estimation** (when you'll hit your budget)
- **Request counts** and error rates

## Quick start

```bash
# 1. Clone
git clone https://github.com/hansakoch/cf-ai-gateway-tracker.git
cd cf-ai-gateway-tracker

# 2. Setup
chmod +x setup.sh
./setup.sh

# 3. Configure
nano ~/.config/cf-ai-gateway/config.json

# 4. Test
python3 ~/.local/bin/cf-ai-gateway-collector --test
```

## Configuration

Edit `~/.config/cf-ai-gateway/config.json`:

```json
{
    "account_id": "your-32-char-cloudflare-account-id",
    "api_token": "your-cloudflare-api-token",
    "gateway_id": "default",
    "monthly_budget_credits": 82000000000,
    "tier_label": "Max Monthly Plan"
}
```

### Getting your credentials

1. **Account ID**: [Cloudflare Dashboard](https://dash.cloudflare.com/) → sidebar
2. **API Token**: [Create Token](https://dash.cloudflare.com/profile/api-tokens) → select:
   - `AI Gateway - Read`
   - `AI Gateway - Edit`

## Route your AI traffic through CF Gateway

### Xiaomi MiMo (Hermes, MiMoCode, Grok CLI)

Update your base URL to route through CF Gateway:

```
# Before
https://token-plan-sgp.xiaomimimo.com/v1

# After (through CF Gateway)
https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/xiaomi/v1
```

### OpenAI-compatible providers

```
# Before
https://api.openai.com/v1

# After
https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openai
```

### Workers AI

```bash
curl -X POST "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions" \
  --header "Authorization: Bearer {api_token}" \
  --header "cf-aig-gateway-id: {gateway_id}" \
  --header "Content-Type: application/json" \
  --data '{"model": "@cf/moonshotai/kimi-k2.6", "messages": [{"role": "user", "content": "Hello"}]}'
```

## CLI usage

```bash
# Test connectivity
python3 ~/.local/bin/cf-ai-gateway-collector --test

# List providers with usage
python3 ~/.local/bin/cf-ai-gateway-collector --providers

# Print full JSON record (for panel)
python3 ~/.local/bin/cf-ai-gateway-collector
```

## Omarchy panel integration

The collector outputs JSON in the Omarchy agents panel schema. Once installed, the panel picks it up automatically via `omarchy-agent-usage-update`.

The applet shows:
- Today's token count and request count
- 7-day usage bar chart
- Per-model token breakdown
- Monthly budget meter with run-out date
- Provider distribution

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  MiMoCode   │     │   Hermes    │     │  Grok CLI   │
│  (laptop)   │     │  (Vultr)    │     │  (Vultr)    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │ CF AI Gateway│
                    │  (proxy)    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼──┐ ┌──────▼──────┐
       │ Xiaomi MiMo │ │OpenAI│ │  Workers AI │
       └─────────────┘ └─────┘ └─────────────┘
                           │
                    ┌──────▼──────┐
                    │  GraphQL    │
                    │  Analytics  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Collector │
                    │   (Python)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ Omarchy     │
                    │ Panel       │
                    └─────────────┘
```

## Why CF AI Gateway?

- **One token to rule them all**: Track Xiaomi, OpenAI, Anthropic, Grok, Workers AI in one place
- **BYOK support**: Bring your own keys for any provider
- **Analytics**: Requests, tokens, costs, errors, cache hits
- **Caching**: Reduce costs by serving repeated requests from cache
- **Rate limiting**: Control your spending
- **Fallbacks**: Route to backup providers on failure
- **Community**: Share your config, compare usage with others

## API Reference

The collector uses Cloudflare's GraphQL API:

```graphql
query {
  viewer {
    accounts(filter: { accountTag: "your-account-id" }) {
      aiGatewayRequestsAdaptiveGroups(
        limit: 1000
        filter: { datetimeHour_geq: "2026-09-01T00:00:00Z" }
      ) {
        count
        sum { tokensIn, tokensOut, costUSD }
        dimensions { model, provider, gateway, ts: datetimeHour }
      }
    }
  }
}
```

## License

MIT
