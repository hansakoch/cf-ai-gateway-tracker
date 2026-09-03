# CF AI Gateway Tracker

Unified AI usage tracking through Cloudflare AI Gateway + MiMo Token Plan. One applet to rule them all — Xiaomi MiMo, OpenAI, Anthropic, Grok, Workers AI, and any BYOK provider.

## What it does

Two data sources, one applet:

- **CF AI Gateway** (primary) — requests, tokens, per-provider breakdown via GraphQL analytics
- **MiMo Token Plan** (supplementary) — credits used, burn rate, run-out date, credit multipliers

Displays everything in your Omarchy panel:
- Daily/monthly token usage across all providers
- Per-provider and per-model breakdowns
- 7-day usage chart
- Run-out date estimation from actual dashboard burn rate
- Credit multipliers (2x pro / 1x std) in limit meter
- MiMo Token Plan details (credits, renewal day, dashboard snapshot)

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

    "mimo_token_plan": {
        "enabled": true,
        "monthly_credits": 82000000000,
        "current_used": 18000000000,
        "dashboard_updated": "2026-09-02",
        "renewal_day": 30,
        "tier_label": "Max Monthly Plan",
        "api_base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
        "models": {
            "mimo-v2.5-pro": {"credit_multiplier": 2, "type": "text"},
            "mimo-v2.5": {"credit_multiplier": 1, "type": "text+image"},
            "mimo-auto": {"credit_multiplier": 1, "type": "text"}
        }
    }
}
```

### Fields

| Field | Description |
|-------|-------------|
| `account_id` | Cloudflare account ID (dashboard sidebar) |
| `api_token` | CF API token with `AI Gateway - Read` permission |
| `gateway_id` | AI Gateway name (default: `default`) |
| `mimo_token_plan.enabled` | Enable MiMo Token Plan tracking |
| `mimo_token_plan.monthly_credits` | Total monthly credits (e.g. 82B) |
| `mimo_token_plan.current_used` | Credits used so far (from dashboard) |
| `mimo_token_plan.dashboard_updated` | Date you checked the dashboard (YYYY-MM-DD) |
| `mimo_token_plan.renewal_day` | Day of month the plan renews (e.g. 30) |
| `mimo_token_plan.tier_label` | Display label (e.g. "Max Monthly Plan") |
| `mimo_token_plan.models` | Per-model credit multipliers and types |

### Getting your credentials

1. **Account ID**: [Cloudflare Dashboard](https://dash.cloudflare.com/) → sidebar
2. **API Token**: [Create Token](https://dash.cloudflare.com/profile/api-tokens) → select:
   - `AI Gateway - Read`
   - `AI Gateway - Edit`

### Updating MiMo Token Plan usage

The collector can't query the Xiaomi dashboard API directly. Update `current_used` and `dashboard_updated` in the config whenever you check the dashboard:

```bash
# Edit config
nano ~/.config/cf-ai-gateway/config.json

# Update these fields:
# "current_used": 25000000000,
# "dashboard_updated": "2026-09-05"

# Clear cache and refresh
rm ~/.cache/cf-ai-gateway/analytics.json
python3 ~/.local/bin/cf-ai-gateway-collector --test
```

The run-out date recalculates from the dashboard snapshot's daily burn rate.

## Route your AI traffic through CF Gateway

### Xiaomi MiMo (Hermes, MiMoCode, Grok CLI)

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
# Test connectivity + MiMo Token Plan status
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
- MiMo Token Plan credit multipliers
- Provider distribution (when traffic routes through CF Gateway)

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
                    │ CF AI Gateway│ ◄── Primary analytics
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
       ┌───────────────────┤
       │                   │
┌──────▼──────┐     ┌──────▼──────┐
│ CF Gateway  │     │ MiMo Token  │ ◄── Supplementary
│ Analytics   │     │ Plan Config │
└──────┬──────┘     └──────┬──────┘
       │                   │
       └─────────┬─────────┘
                 │
          ┌──────▼──────┐
          │  Collector  │
          │  (unified)  │
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

## License

MIT
