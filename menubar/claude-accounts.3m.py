#!/usr/bin/env python3
# <xbar.title>Claude accounts</xbar.title>
# <xbar.desc>Usage for every Claude account in claude-accounts, with one-click switching. Optional Codex usage from codex-lb.</xbar.desc>
# <xbar.author.github>Spshulem</xbar.author.github>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""SwiftBar plugin: Claude (and optionally Codex) usage in the menu bar.

Runs every 3 minutes (the file name says so), which is also the floor the
Claude usage endpoint tolerates. "Refresh now" forces a fresh read.

  Claude  `claude-accounts status --json`, one row per account
  Codex   optional, from codex-lb, configured in ~/.claude-accounts/menubar.json:
            {"codex_lb_url": "http://host:2455", "codex_lb_api_key": "sk-clb-..."}
              the pool's combined usage, over codex-lb's HTTP API
            {"codex_lb_ssh": "user@host", "codex_lb_container": "codex-lb"}
              every pooled account, read from codex-lb's database over SSH
          The last good Codex reading is cached, so an outage shows stale
          numbers with a warning instead of an empty menu.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
ROOT = HOME / ".claude-accounts"
CLAUDE_ACCOUNTS = ROOT / "bin" / "claude-accounts"
CONFIG_FILE = ROOT / "menubar.json"
CACHE = HOME / ".cache" / "claude-accounts"
CODEX_CACHE = CACHE / "codex.json"
SELF = Path(__file__).resolve()

CODEX_QUERY = r'''
import sqlite3, json
c = sqlite3.connect("/var/lib/codex-lb/store.db")
out = []
for aid, email, status, policy in c.execute(
        "select id, email, status, routing_policy from accounts order by email"):
    windows = []
    for w in ("primary", "secondary"):
        r = c.execute("select used_percent, reset_at, window_minutes from usage_history "
                      "where account_id=? and window=? order by recorded_at desc limit 1",
                      (aid, w)).fetchone()
        if r and r[2]:
            windows.append({"minutes": r[2], "pct": r[0], "reset": r[1]})
    out.append({"email": email, "status": status, "policy": policy, "windows": windows})
print(json.dumps(out))
'''


def config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


# ------------------------------------------------------------------ data

def claude(refresh: bool) -> dict | None:
    args = [sys.executable, str(CLAUDE_ACCOUNTS), "status", "--json"] + (["--refresh"] if refresh else [])
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=90)
        return json.loads(r.stdout)
    except Exception:
        return None


def ssl_context() -> ssl.SSLContext:
    for path in ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"):
        try:
            return ssl.create_default_context(cafile=path)
        except Exception:
            continue
    return ssl.create_default_context()


def codex_over_http(cfg: dict) -> list:
    """The pool as one row: codex-lb's API key only sees combined usage."""
    req = urllib.request.Request(cfg["codex_lb_url"].rstrip("/") + "/v1/usage",
                                 headers={"Authorization": f"Bearer {cfg['codex_lb_api_key']}"})
    with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:
        data = json.loads(r.read())
    windows = []
    for lim in data.get("upstream_limits") or data.get("limits") or []:
        cap, used = lim.get("max_value"), lim.get("current_value")
        if not cap or used is None:
            continue
        minutes = {"5h": 300, "7d": 10080, "30d": 43200}.get(lim.get("limit_window"), 0)
        windows.append({"minutes": minutes, "label": lim.get("limit_window"),
                        "pct": 100.0 * used / cap, "reset": lim.get("reset_at")})
    return [{"email": "Pool (all accounts)", "status": "active", "policy": "", "windows": windows}]


def codex_over_ssh(cfg: dict) -> list:
    """Every pooled account, from codex-lb's own database in its container."""
    container = cfg.get("codex_lb_container") or "codex-lb"
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", cfg["codex_lb_ssh"],
         f"docker exec -i {container} python3 -"],
        input=CODEX_QUERY, capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)


def codex(refresh: bool) -> tuple[list | None, float | None, bool]:
    """(accounts, age_seconds, configured). Reads at most every 3 minutes unless forced."""
    cfg = config()
    if cfg.get("codex_lb_ssh"):
        fetch = codex_over_ssh
    elif cfg.get("codex_lb_url") and cfg.get("codex_lb_api_key"):
        fetch = codex_over_http
    else:
        return None, None, False
    cached, at = None, None
    try:
        blob = json.loads(CODEX_CACHE.read_text())
        cached, at = blob["accounts"], blob["at"]
    except Exception:
        pass
    if cached is not None and not refresh and time.time() - at < 170:
        return cached, time.time() - at, True
    try:
        accounts = fetch(cfg)
        CACHE.mkdir(parents=True, exist_ok=True)
        CODEX_CACHE.write_text(json.dumps({"at": time.time(), "accounts": accounts}))
        return accounts, 0.0, True
    except Exception:
        return cached, (time.time() - at) if at else None, True


# ------------------------------------------------------------ formatting

def when(value) -> str:
    """Local, short: 11:40pm today, 'Mon 10am' otherwise."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        dt = dt.astimezone()
    except Exception:
        return ""
    now = datetime.now().astimezone()
    clock = dt.strftime("%-I:%M%p").lower().replace(":00", "")
    return clock if dt.date() == now.date() else f"{dt.strftime('%a')} {clock}"


def color(pct) -> str:
    if not isinstance(pct, (int, float)):
        return "#8e8e93"
    if pct >= 90:
        return "#ff453a"
    if pct >= 70:
        return "#ff9f0a"
    return "#32d74b"


def bar(pct, width=10) -> str:
    if not isinstance(pct, (int, float)):
        return "·" * width
    filled = round(max(0, min(100, pct)) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def window_name(w: dict) -> str:
    return {300: "5-hour", 10080: "Weekly", 43200: "Monthly"}.get(w.get("minutes"), w.get("label") or "Window")


def line(text: str, **params) -> None:
    extras = " ".join(f"{k}={v}" for k, v in params.items() if v not in ("", None))
    print(f"{text} | {extras}" if extras else text)


# ---------------------------------------------------------------- render

def render(refresh: bool) -> None:
    c = claude(refresh)
    x, x_age, x_configured = codex(refresh)
    cfg = config()

    # Title: the active Claude account's worst window, and how many Codex accounts can still work.
    title_parts = []
    active_worst = None
    if c:
        for a in c["accounts"]:
            if a["active"] and a["usage"].get("ok"):
                vals = [w["pct"] for w in a["usage"]["windows"] if isinstance(w.get("pct"), (int, float))]
                active_worst = max(vals) if vals else 0
        title_parts.append(f"✳ {active_worst:.0f}%" if active_worst is not None else "✳ ?")
    usable = None
    if x is not None and cfg.get("codex_lb_ssh"):
        usable = sum(1 for a in x if a["status"] == "active")
        title_parts.append(f"◎ {usable}/{len(x)}")
    line("  ".join(title_parts) or "Claude",
         color=color(active_worst) if active_worst is not None and active_worst >= 70 else "")

    print("---")

    # Claude
    if not c:
        line("Claude: claude-accounts not reachable", color="#ff453a")
        line("Reinstall: claude-accounts install", color="#8e8e93", size=11)
    else:
        line(f"Claude — active: {c['active']}", size=13)
        for a in c["accounts"]:
            who = a["identity"] or "(not logged in)"
            mark = "✓ " if a["active"] else "   "
            u = a["usage"]
            head = f"{mark}{a['label']} · {who}"
            if not u.get("ok"):
                line(head, color="#8e8e93")
                line(f"--{u.get('error', 'no data')}", color="#8e8e93")
            else:
                worst = max([w["pct"] for w in u["windows"] if isinstance(w.get("pct"), (int, float))], default=0)
                line(head, color=color(worst))
                for w in u["windows"]:
                    name = {"session": "Session (5h)", "weekly": "Weekly"}.get(w["name"], w["name"].replace("weekly:", "Weekly · "))
                    reset = when(w.get("resets_at"))
                    line(f"   {bar(w.get('pct'))} {w.get('pct', 0):>3.0f}%  {name}"
                         + (f" · resets {reset}" if reset else ""),
                         font="Menlo", size=11, color=color(w.get("pct")))
            if not a["active"] and u.get("ok"):
                line(f"   ↪ Switch Claude to {a['label']}", bash=str(CLAUDE_ACCOUNTS),
                     param1="use", param2=a["label"], terminal="false", refresh="true", size=11)
            if c.get("conductor") and a["label"] != "default" and not a["token"]:
                line(f"   ⚠ no Conductor token: claude-accounts token {a['label']}", color="#ff9f0a", size=11)

    # Codex (only when configured)
    if x_configured:
        print("---")
        if x is None:
            line("Codex: codex-lb unreachable", color="#ff453a")
        else:
            stale = x_age is not None and x_age > 600
            if usable is not None:
                line(f"Codex — {usable}/{len(x)} accounts usable (codex-lb)", size=13)
            else:
                line("Codex — codex-lb", size=13)
            if stale:
                line(f"   ⚠ codex-lb unreachable; numbers are {x_age/60:.0f} min old", color="#ff9f0a")
            for a in x:
                used = max([w["pct"] for w in a["windows"] if isinstance(w.get("pct"), (int, float))], default=None)
                status = {"active": "", "rate_limited": " · limited", "paused": " · paused",
                          "deactivated": " · deactivated"}.get(a["status"], f" · {a['status']}")
                policy = " · protected" if a.get("policy") == "preserve" else ""
                line(f"{a['email']}{status}{policy}", color=color(used) if a["status"] == "active" else "#8e8e93")
                for w in a["windows"]:
                    reset = when(w.get("reset"))
                    line(f"   {bar(w['pct'])} {w['pct']:>3.0f}%  {window_name(w)}"
                         + (f" · resets {reset}" if reset else ""),
                         font="Menlo", size=11, color=color(w["pct"]))
            if cfg.get("codex_lb_url"):
                line("Open codex-lb dashboard", href=cfg["codex_lb_url"])

    print("---")
    line("Refresh now", bash=str(SELF), param1="--refresh", terminal="false", refresh="true")
    line("Failover log", bash="/usr/bin/open", param1="-t", param2=str(ROOT / "auto.log"),
         terminal="false")
    line(f"Updated {datetime.now().strftime('%-I:%M%p').lower()}", color="#8e8e93", size=11)


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        # Invoked by the "Refresh now" item: warm both caches, print nothing.
        # SwiftBar then re-runs the plugin normally and it reads the fresh data.
        claude(refresh=True)
        codex(refresh=True)
    else:
        render(refresh=False)
