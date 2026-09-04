#!/usr/bin/env python3
"""CF AI Gateway + MiMo Token Plan — Unified Usage Collector

Two data sources, one output:
  1. Cloudflare AI Gateway GraphQL analytics (all routed providers)
  2. MiMo Token Plan live data via browser CDP (credits, burn rate, run-out)

Outputs JSON compatible with the Omarchy agents panel schema.

Usage:
    python3 collector.py              # Print JSON (cached, 30min TTL)
    python3 collector.py --live       # Force fresh fetch, skip cache
    python3 collector.py --test       # Test connectivity
    python3 collector.py --providers  # List providers with usage

Config: ~/.config/cf-ai-gateway/config.json
Cache:  ~/.cache/cf-ai-gateway/collector.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

AGENT_ID = "cf-ai-gateway"
AGENT_NAME = "CF AI Gateway"
CONFIG_PATH = Path.home() / ".config" / "cf-ai-gateway" / "config.json"
CACHE_PATH = Path.home() / ".cache" / "cf-ai-gateway" / "collector.json"
CACHE_TTL = 1800  # 30 minutes

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
CDP_PORT = 9222

# ── GraphQL queries ──────────────────────────────────────────────────

QUERY_HOURLY = """
query($accountId: String!, $start: String!, $end: String!, $limit: Int!) {
  viewer {
    accounts(filter: { accountTag: $accountId }) {
      aiGatewayRequestsAdaptiveGroups(
        limit: $limit
        filter: { datetimeHour_geq: $start, datetimeHour_leq: $end }
      ) {
        count
        sum { tokensIn tokensOut }
        dimensions { model provider gateway ts: datetimeHour }
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
        sum { tokensIn tokensOut }
        dimensions { date: datetimeDay model provider }
      }
    }
  }
}
"""


# ── Config ───────────────────────────────────────────────────────────

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


# ── HTTP helpers ─────────────────────────────────────────────────────

def http_json(url: str, token: str = "", method: str = "GET",
              body: bytes | None = None, timeout: int = 10) -> dict | None:
    req = Request(url, data=body, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def graphql(query: str, variables: dict, token: str) -> dict | None:
    body = json.dumps({"query": query, "variables": variables}).encode()
    return http_json(GRAPHQL_URL, token=token, method="POST", body=body, timeout=15)


# ── Cache ────────────────────────────────────────────────────────────

def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        if time.time() - CACHE_PATH.stat().st_mtime > CACHE_TTL:
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


# ── MiMo Token Plan (live via browser CDP) ───────────────────────────

def fetch_mimo_plan_live() -> dict | None:
    """Fetch live MiMo Token Plan data from the Xiaomi dashboard via Chrome DevTools Protocol.

    Uses the running Chromium's existing session cookies — no API key needed.
    Returns parsed API response or None if unavailable.
    """
    import subprocess
    try:
        pages = http_json(f"http://localhost:{CDP_PORT}/json", timeout=3)
        if not pages:
            return None
    except Exception:
        return None

    ws_url = None
    for p in (pages or []):
        if p.get("webSocketDebuggerUrl"):
            ws_url = p["webSocketDebuggerUrl"]
            if "xiaomimimo.com" in p.get("url", ""):
                break

    if not ws_url:
        return None

    js = """
    (async () => {
        try {
            const [d, u] = await Promise.all([
                fetch('https://platform.xiaomimimo.com/api/v1/tokenPlan/detail', {credentials:'include'}).then(r => r.json()),
                fetch('https://platform.xiaomimimo.com/api/v1/tokenPlan/usage', {credentials:'include'}).then(r => r.json())
            ]);
            return JSON.stringify({detail: d, usage: u});
        } catch(e) { return JSON.stringify({error: e.message}); }
    })()
    """
    script = f"""
    const ws = new WebSocket("{ws_url}");
    ws.onopen = () => ws.send(JSON.stringify({{id:1, method:"Runtime.evaluate", params:{json.dumps({"expression": js, "awaitPromise": True, "returnByValue": True})}}}));
    ws.onmessage = (e) => {{ console.log(e.data); ws.close(); process.exit(0); }};
    ws.onerror = () => process.exit(1);
    setTimeout(() => process.exit(1), 10000);
    """
    try:
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            result = json.loads(r.stdout.strip())
            value = result.get("result", {}).get("result", {}).get("value", "")
            if value:
                data = json.loads(value)
                if not data.get("error") and data.get("detail", {}).get("code") != 401:
                    return data
    except Exception:
        pass
    return None


def load_mimo_plan() -> dict | None:
    """Load MiMo plan: live from browser, then cached file, then config."""
    plan_cache = Path.home() / ".cache" / "cf-ai-gateway" / "mimo-plan.json"

    # Try live fetch
    live = fetch_mimo_plan_live()
    if live:
        live["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        try:
            plan_cache.parent.mkdir(parents=True, exist_ok=True)
            plan_cache.write_text(json.dumps(live, indent=2))
        except Exception:
            pass
        return live

    # Try cached plan (valid for 6 hours)
    if plan_cache.exists():
        try:
            if time.time() - plan_cache.stat().st_mtime < 21600:
                return json.loads(plan_cache.read_text())
        except Exception:
            pass

    return None


# ── CF AI Gateway analytics ─────────────────────────────────────────

def fetch_gateway_analytics(cfg: dict) -> dict | None:
    account_id = cfg.get("account_id", "")
    token = cfg.get("api_token", "")
    if not account_id or not token:
        return None

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    max_lookback = now - timedelta(weeks=4, days=3)
    if month_start < max_lookback:
        month_start = max_lookback

    # Today's hourly data
    hourly_groups = []
    hourly = graphql(QUERY_HOURLY, {
        "accountId": account_id,
        "start": today_start.isoformat(),
        "end": now.isoformat(),
        "limit": 5000,
    }, token)
    if hourly and hourly.get("data"):
        hourly_groups = (
            hourly["data"].get("viewer", {})
            .get("accounts", [{}])[0]
            .get("aiGatewayRequestsAdaptiveGroups", [])
        )

    # Month's daily data
    daily_groups = []
    daily = graphql(QUERY_DAILY, {
        "accountId": account_id,
        "start": month_start.isoformat(),
        "end": now.isoformat(),
        "limit": 5000,
    }, token)
    if daily and daily.get("data"):
        daily_groups = (
            daily["data"].get("viewer", {})
            .get("accounts", [{}])[0]
            .get("aiGatewayRequestsAdaptiveGroups", [])
        )

    # Aggregate today
    today_requests = 0
    today_tokens_in = 0
    today_tokens_out = 0
    today_by_model: dict[str, int] = {}

    for g in hourly_groups:
        count = g.get("count", 0)
        s = g.get("sum", {})
        ti = s.get("tokensIn", 0) or 0
        to = s.get("tokensOut", 0) or 0
        model = g.get("dimensions", {}).get("model", "unknown")
        today_requests += count
        today_tokens_in += ti
        today_tokens_out += to
        today_by_model[model] = today_by_model.get(model, 0) + ti + to

    # Aggregate month
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
        "daily_map": daily_map,
        "month_requests": month_requests,
        "month_tokens_in": month_tokens_in,
        "month_tokens_out": month_tokens_out,
        "month_by_model": month_by_model,
        "month_by_provider": month_by_provider,
    }


def fetch_gateways(cfg: dict) -> list[dict]:
    account_id = cfg.get("account_id", "")
    token = cfg.get("api_token", "")
    if not account_id or not token:
        return []
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai-gateway/gateways"
    data = http_json(url, token=token, timeout=8)
    if data and data.get("success"):
        return data.get("result", [])
    return []


# ── Collect (main logic) ─────────────────────────────────────────────

def collect(cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    # Fetch CF Gateway analytics
    gw = fetch_gateway_analytics(cfg)
    gateways = fetch_gateways(cfg)
    connected = gw is not None or len(gateways) > 0

    # Fetch MiMo Token Plan (live from browser)
    plan = load_mimo_plan()

    # Build gateway analytics record
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

    has_traffic = today_requests > 0 or month_requests > 0

    record = {
        "schemaVersion": 1,
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "updatedAt": now.isoformat(),
        "ready": connected,
        "hasLocalStats": True,
        "todayPrompts": today_requests,
        "todaySessions": 0,
        "todayTotalTokens": today_tokens,
        "todayTokensByModel": today_by_model,
        "recentDays": recent_days,
        "totalPrompts": month_requests,
        "totalSessions": 0,
        "activeDays": max(len([d for d in daily_map.values() if d > 0]), 1 if connected else 0),
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
            {"id": g["id"], "isDefault": g.get("is_default", False),
             "billingMode": g.get("workers_ai_billing_mode", "unknown"),
             "createdAt": g.get("created_at", "")}
            for g in gateways
        ]

    # ── MiMo Token Plan limits ───────────────────────────────────────
    if plan:
        plan_detail = plan.get("detail", {}).get("data", {})
        plan_usage = plan.get("usage", {}).get("data", {})
        month_items = plan_usage.get("monthUsage", {}).get("items", [])

        if month_items:
            item = month_items[0]
            percent = item.get("percent", 0)
            used = item.get("used", 0)
            expires = plan_detail.get("currentPeriodEnd", "")
            resets_at = ""
            if expires:
                try:
                    resets_at = expires.replace(" ", "T") + "+00:00"
                except Exception:
                    resets_at = _month_end_iso()
            else:
                resets_at = _month_end_iso()

            record["limits"].append({
                "label": "Monthly",
                "title": plan_detail.get("planName", "MiMo Token Plan"),
                "percent": percent,
                "used": used,
                "resetsAt": resets_at,
            })

            # Tier label with days left
            plan_name = plan_detail.get("planName", "MiMo")
            auto = plan_detail.get("enableAutoRenew", False)
            renew_str = " Auto-Renewal" if auto else ""
            try:
                end_date = datetime.fromisoformat(expires.replace(" ", "T")).date()
                days_left = max((end_date - datetime.now(timezone.utc).date()).days, 0)
                record["tierLabel"] = f"{plan_name}{renew_str} · {days_left}d left"
            except Exception:
                record["tierLabel"] = f"{plan_name}{renew_str}"

    elif not has_traffic and gateways:
        record["tierLabel"] = f"{len(gateways)} gateways · no traffic yet"

    return record


def _month_end_iso() -> str:
    now = datetime.now(timezone.utc)
    if now.month == 12:
        end = now.replace(year=now.year + 1, month=1, day=1)
    else:
        end = now.replace(month=now.month + 1, day=1)
    return end.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


# ── CLI commands ─────────────────────────────────────────────────────

def cmd_test(cfg: dict) -> None:
    account_id = cfg.get("account_id", "")
    token = cfg.get("api_token", "")
    if not account_id or not token:
        print("✗ Missing account_id or api_token in config")
        print(f"  Config: {CONFIG_PATH}")
        return
    print(f"Account: {account_id[:8]}...")
    print(f"Token: {token[:8]}...")

    # Test gateway
    now = datetime.now(timezone.utc)
    result = graphql(QUERY_HOURLY, {
        "accountId": account_id,
        "start": (now - timedelta(hours=1)).isoformat(),
        "end": now.isoformat(),
        "limit": 10,
    }, token)
    if result and result.get("data"):
        groups = (
            result["data"].get("viewer", {})
            .get("accounts", [{}])[0]
            .get("aiGatewayRequestsAdaptiveGroups", [])
        )
        total = sum(g.get("count", 0) for g in groups)
        print(f"✓ Gateway connected — {total} requests in last hour")
    else:
        print("✗ Gateway: no response")

    # Test MiMo plan
    plan = load_mimo_plan()
    if plan:
        detail = plan.get("detail", {}).get("data", {})
        usage = plan.get("usage", {}).get("data", {})
        items = usage.get("monthUsage", {}).get("items", [])
        name = detail.get("planName", "Unknown")
        if items:
            pct = items[0].get("percent", 0)
            print(f"✓ MiMo Token Plan: {name} — {pct*100:.1f}% used")
        else:
            print(f"✓ MiMo Token Plan: {name} — no usage data")
    else:
        print("⚠ MiMo Token Plan: not available (open xiaomimimo.com in Chromium)")


def cmd_providers(cfg: dict) -> None:
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

    gateways = record.get("gateways", [])
    if gateways:
        print(f"\n=== AI Gateways ({len(gateways)}) ===")
        for g in gateways:
            default = " (default)" if g.get("isDefault") else ""
            print(f"  {g['id']}{default}: {g.get('billingMode', '?')}")

    limits = record.get("limits", [])
    if limits:
        for lim in limits:
            pct = lim.get("percent", 0) * 100
            print(f"\n=== {lim.get('title', 'Token Plan')} ===")
            print(f"  Used: {pct:.1f}%")
            print(f"  Resets: {lim.get('resetsAt', '?')}")

    print(f"\nToday: {record['todayTotalTokens']:,} tokens, {record['todayPrompts']} requests")
    if record.get("tierLabel"):
        print(f"Status: {record['tierLabel']}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    cfg = load_config()

    if "--test" in sys.argv:
        cmd_test(cfg)
        return

    if "--providers" in sys.argv:
        cmd_providers(cfg)
        return

    # Cache: --live skips it
    if "--live" not in sys.argv:
        cached = load_cache()
        if cached:
            print(json.dumps(cached))
            return

    record = collect(cfg)
    save_cache(record)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
