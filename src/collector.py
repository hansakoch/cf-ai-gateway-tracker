#!/usr/bin/env python3
"""CF AI Gateway + MiMo Token Plan — Unified Usage Collector

Primary source: Cloudflare AI Gateway GraphQL analytics (all providers).
Supplementary: MiMo Token Plan details (credits, burn rate, run-out date).

Outputs a JSON record compatible with the Omarchy agents panel schema.

Usage:
    python3 collector.py                     # Print JSON to stdout
    python3 collector.py --test              # Test connectivity
    python3 collector.py --providers         # List providers with usage

Config: ~/.config/cf-ai-gateway/config.json
{
    "account_id": "your-32-char-cloudflare-account-id",
    "api_token": "your-cloudflare-api-token-with-ai-gateway-permission",
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
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

AGENT_ID = "cf-ai-gateway"
AGENT_NAME = "CF AI Gateway"
CONFIG_PATH = Path.home() / ".config" / "cf-ai-gateway" / "config.json"
CACHE_PATH = Path.home() / ".cache" / "cf-ai-gateway" / "analytics.json"
CACHE_TTL = 300  # 5 minutes

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"

# ── GraphQL queries ──────────────────────────────────────────────────

QUERY_USAGE = """
query($accountId: String!, $start: String!, $end: String!, $limit: Int!) {
  viewer {
    accounts(filter: { accountTag: $accountId }) {
      aiGatewayRequestsAdaptiveGroups(
        limit: $limit
        filter: { datetimeHour_geq: $start, datetimeHour_leq: $end }
      ) {
        count
        sum {
          tokensIn
          tokensOut
        }
        dimensions {
          model
          provider
          gateway
          ts: datetimeHour
        }
      }
    }
  }
}
"""

QUERY_DAILY = """
query($accountId: String!, $start: String!, $end: String!, $limit: Int!) {
  viewer {
    accounts(filter: { accountTag: $accountId }) {
      aiGatewayRequestsAdaptiveGroups(
        limit: $limit
        filter: { datetimeHour_geq: $start, datetimeHour_leq: $end }
      ) {
        count
        sum {
          tokensIn
          tokensOut
        }
        dimensions {
          date: datetimeDay
          model
          provider
        }
      }
    }
  }
}
"""


def load_config() -> dict:
    defaults = {
        "account_id": "",
        "api_token": "",
        "gateway_id": "default",
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except Exception:
            pass
    return defaults


def graphql(query: str, variables: dict, token: str) -> dict:
    """Execute a GraphQL query against the Cloudflare API."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = Request(GRAPHQL_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        errors = data.get("errors")
        if errors and any(e for e in errors if e is not None):
            raise RuntimeError(json.dumps(errors))
        return data
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        mtime = CACHE_PATH.stat().st_mtime
        if time.time() - mtime > CACHE_TTL:
            return None
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(data: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def month_end_iso() -> str:
    now = datetime.now(timezone.utc)
    if now.month == 12:
        end = now.replace(year=now.year + 1, month=1, day=1)
    else:
        end = now.replace(month=now.month + 1, day=1)
    return end.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def collect_gateway(cfg: dict) -> dict | None:
    """Collect usage from CF AI Gateway GraphQL analytics."""
    account_id = cfg.get("account_id", "")
    token = cfg.get("api_token", "")
    if not account_id or not token:
        return None

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    max_lookback = now - timedelta(weeks=4, days=3)
    month_start = today_start.replace(day=1)
    if month_start < max_lookback:
        month_start = max_lookback

    # Fetch hourly data for today
    hourly_groups = []
    try:
        hourly = graphql(QUERY_USAGE, {
            "accountId": account_id,
            "start": today_start.isoformat(),
            "end": now.isoformat(),
            "limit": 5000,
        }, token)
        hourly_groups = (
            hourly.get("data", {})
            .get("viewer", {})
            .get("accounts", [{}])[0]
            .get("aiGatewayRequestsAdaptiveGroups", [])
        )
    except RuntimeError:
        pass

    # Fetch daily data for the month
    daily_groups = []
    try:
        daily = graphql(QUERY_DAILY, {
            "accountId": account_id,
            "start": month_start.isoformat(),
            "end": now.isoformat(),
            "limit": 5000,
        }, token)
        daily_groups = (
            daily.get("data", {})
            .get("viewer", {})
            .get("accounts", [{}])[0]
            .get("aiGatewayRequestsAdaptiveGroups", [])
        )
    except RuntimeError:
        pass

    # Aggregate today
    today_requests = 0
    today_tokens_in = 0
    today_tokens_out = 0
    today_by_model: dict[str, int] = {}
    today_by_provider: dict[str, int] = {}

    for g in hourly_groups:
        count = g.get("count", 0)
        s = g.get("sum", {})
        ti = s.get("tokensIn", 0) or 0
        to = s.get("tokensOut", 0) or 0
        dims = g.get("dimensions", {})
        model = dims.get("model", "unknown")
        provider = dims.get("provider", "unknown")
        today_requests += count
        today_tokens_in += ti
        today_tokens_out += to
        total = ti + to
        today_by_model[model] = today_by_model.get(model, 0) + total
        today_by_provider[provider] = today_by_provider.get(provider, 0) + total

    # Aggregate daily
    daily_map: dict[str, int] = {}
    month_requests = 0
    month_tokens_in = 0
    month_tokens_out = 0
    month_by_model: dict[str, dict] = {}
    month_by_provider: dict[str, int] = {}

    for g in daily_groups:
        count = g.get("count", 0)
        s = g.get("sum", {})
        ti = s.get("tokensIn", 0) or 0
        to = s.get("tokensOut", 0) or 0
        dims = g.get("dimensions", {})
        date = dims.get("date", "")
        model = dims.get("model", "unknown")
        provider = dims.get("provider", "unknown")
        month_requests += count
        month_tokens_in += ti
        month_tokens_out += to
        total = ti + to
        if date:
            daily_map[date] = daily_map.get(date, 0) + total
        if model not in month_by_model:
            month_by_model[model] = {"inputTokens": 0, "outputTokens": 0, "requests": 0}
        month_by_model[model]["inputTokens"] += ti
        month_by_model[model]["outputTokens"] += to
        month_by_model[model]["requests"] += count
        month_by_provider[provider] = month_by_provider.get(provider, 0) + total

    return {
        "today_requests": today_requests,
        "today_tokens_in": today_tokens_in,
        "today_tokens_out": today_tokens_out,
        "today_by_model": today_by_model,
        "today_by_provider": today_by_provider,
        "daily_map": daily_map,
        "month_requests": month_requests,
        "month_tokens_in": month_tokens_in,
        "month_tokens_out": month_tokens_out,
        "month_by_model": month_by_model,
        "month_by_provider": month_by_provider,
    }


def collect_gateways(cfg: dict) -> list[dict]:
    """Fetch AI Gateway list from CF API."""
    account_id = cfg.get("account_id", "")
    token = cfg.get("api_token", "")
    if not account_id or not token:
        return []

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai-gateway/gateways"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if data.get("success"):
            return data.get("result", [])
    except Exception:
        pass
    return []


def collect(cfg: dict) -> dict:
    """Collect CF AI Gateway usage analytics."""
    now = datetime.now(timezone.utc)
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    # ── CF AI Gateway analytics ──────────────────────────────────────
    gw = collect_gateway(cfg)
    gateways = collect_gateways(cfg)

    today_tokens = 0
    today_requests = 0
    today_by_model: dict[str, int] = {}
    daily_map: dict[str, int] = {}
    month_requests = 0
    month_by_model: dict[str, dict] = {}
    month_by_provider: dict[str, int] = {}

    if gw:
        today_tokens = gw["today_tokens_in"] + gw["today_tokens_out"]
        today_requests = gw["today_requests"]
        today_by_model = gw["today_by_model"]
        daily_map = gw["daily_map"]
        month_requests = gw["month_requests"]
        month_by_model = gw["month_by_model"]
        month_by_provider = gw["month_by_provider"]

    recent_days = [{"date": d, "messageCount": daily_map.get(d, 0)} for d in dates]

    model_usage = {}
    for model, bucket in month_by_model.items():
        model_usage[model] = {
            "inputTokens": bucket["inputTokens"],
            "outputTokens": bucket["outputTokens"],
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
        }

    # ── Build record ─────────────────────────────────────────────────
    record = {
        "schemaVersion": 1,
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "updatedAt": now.isoformat(),
        "ready": True,
        "hasLocalStats": True,
        "todayPrompts": today_requests,
        "todaySessions": 0,
        "todayTotalTokens": today_tokens,
        "todayTokensByModel": today_by_model,
        "recentDays": recent_days,
        "totalPrompts": month_requests,
        "totalSessions": 0,
        "activeDays": len([d for d in daily_map.values() if d > 0]),
        "activeDates": sorted(daily_map.keys()),
        "modelUsage": model_usage,
        "limits": [],
        "tierLabel": "",
        "providers": month_by_provider,
        "todayTokensIn": gw["today_tokens_in"] if gw else 0,
        "todayTokensOut": gw["today_tokens_out"] if gw else 0,
    }

    # Gateway list
    if gateways:
        record["gateways"] = [
            {
                "id": g["id"],
                "isDefault": g.get("is_default", False),
                "billingMode": g.get("workers_ai_billing_mode", "unknown"),
                "createdAt": g.get("created_at", ""),
            }
            for g in gateways
        ]

    return record


def test_connection(cfg: dict) -> bool:
    """Test CF AI Gateway connectivity."""
    account_id = cfg.get("account_id", "")
    token = cfg.get("api_token", "")

    if not account_id or not token:
        print("✗ Missing account_id or api_token in config")
        return False

    print(f"Account: {account_id[:8]}...")
    print(f"Token: {token[:8]}...")

    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        result = graphql(QUERY_USAGE, {
            "accountId": account_id,
            "start": start.isoformat(),
            "end": now.isoformat(),
            "limit": 10,
        }, token)
        groups = (
            result.get("data", {})
            .get("viewer", {})
            .get("accounts", [{}])[0]
            .get("aiGatewayRequestsAdaptiveGroups", [])
        )
        total = sum(g.get("count", 0) for g in groups)
        print(f"✓ Gateway connected — {total} requests in last hour")
    except RuntimeError as e:
        print(f"⚠ Gateway: {e}")

    return True


def list_providers(cfg: dict) -> None:
    """List providers with usage."""
    record = collect(cfg)
    providers = record.get("providers", {})
    models = record.get("modelUsage", {})

    print("=== CF AI Gateway — Providers (this month) ===")
    if providers:
        for provider, tokens in sorted(providers.items(), key=lambda x: -x[1]):
            print(f"  {provider}: {tokens:,} tokens")
    else:
        print("  (no data — route traffic through CF Gateway)")

    print(f"\n=== Models ===")
    if models:
        for model, bucket in sorted(models.items(), key=lambda x: -(x[1]["inputTokens"] + x[1]["outputTokens"])):
            total = bucket["inputTokens"] + bucket["outputTokens"]
            print(f"  {model}: {total:,} tokens")
    else:
        print("  (no data)")

    # Gateway info
    gateways = record.get("gateways", [])
    if gateways:
        print(f"\n=== AI Gateways ({len(gateways)}) ===")
        for g in gateways:
            default = " (default)" if g.get("isDefault") else ""
            print(f"  {g['id']}{default}: {g.get('billingMode', '?')}")

    print(f"\nToday: {record['todayTotalTokens']:,} tokens, {record['todayPrompts']} requests")


def main():
    cfg = load_config()

    if "--test" in sys.argv:
        test_connection(cfg)
        return

    if "--providers" in sys.argv:
        list_providers(cfg)
        return

    # Try cache first
    cached = load_cache()
    if cached:
        print(json.dumps(cached))
        return

    record = collect(cfg)
    save_cache(record)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
