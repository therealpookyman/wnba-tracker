"""WNBA halftime tracker — cloud edition (runs in GitHub Actions).

Same logic as the local tracker: at each poll, snapshot halftime score,
pregame spread, and Kalshi orderbook depth (game winner + 2H winner) for any
WNBA game currently at halftime; log finals with quarter scores once.
Appends to data/wnba_tracking.jsonl and rewrites data/wnba_status.html.
"""
import json, os
from datetime import datetime, timezone
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data/wnba_tracking.jsonl")
STATUS = os.path.join(BASE, "data/wnba_status.html")
KAPI = "https://api.elections.kalshi.com/trade-api/v2"
E2K = {"POR": "PDX", "CON": "CONN"}  # ESPN abbrev -> Kalshi code


def kalshi_tickers(sess, series):
    out = set()
    r = sess.get(f"{KAPI}/events", params={"series_ticker": series, "status": "open",
                                           "limit": 100, "with_nested_markets": "true"}, timeout=20)
    r.raise_for_status()
    for ev in r.json().get("events", []):
        for m in ev.get("markets") or []:
            out.add(m["ticker"])
    return out


def orderbook(sess, ticker, depth=5):
    r = sess.get(f"{KAPI}/markets/{ticker}/orderbook", params={"depth": depth}, timeout=20)
    if r.status_code != 200:
        return None
    ob = r.json().get("orderbook_fp") or {}
    yes = [(float(p), float(q)) for p, q in (ob.get("yes_dollars") or [])]
    no = [(float(p), float(q)) for p, q in (ob.get("no_dollars") or [])]
    best_bid = max((p for p, _ in yes), default=None)
    best_no = max((p for p, _ in no), default=None)
    return {"yes_bid": best_bid, "yes_ask": round(1 - best_no, 4) if best_no is not None else None,
            "yes_depth": yes, "no_depth": no}


def pregame_spread(sess, eid):
    url = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/events/{eid}/competitions/{eid}/odds"
    try:
        r = sess.get(url, timeout=20)
        r.raise_for_status()
        spreads = sorted(it["spread"] for it in r.json().get("items", []) if it.get("spread") is not None)
        return spreads[len(spreads) // 2] if spreads else None
    except Exception:
        return None


def render_status(games):
    snaps, finals = [], []
    if os.path.exists(OUT):
        for line in open(OUT):
            r = json.loads(line)
            (snaps if r.get("type") == "halftime_snapshot" else finals).append(r)
    by_game = {}
    for r in snaps:
        by_game.setdefault((r["away"], r["home"]), []).append(r)

    def fmt(k):
        b, a = k.get("yes_bid"), k.get("yes_ask")
        return f"{b:.2f}/{a:.2f}" if b is not None and a is not None else "—"

    rows = []
    for (away, home), rs in by_game.items():
        last = rs[-1]
        game_q, h2_q = [], []
        for t, k in (last.get("kalshi") or {}).items():
            side = t.rsplit("-", 1)[1]
            if side == "TIE":
                continue
            (game_q if t.startswith("KXWNBAGAME") else h2_q).append(f"{side} {fmt(k)}")
        rows.append(f"<tr><td>{away} @ {home}</td><td>{last['away_h1']}–{last['home_h1']}</td>"
                    f"<td>{last.get('spread_home')}</td><td>{len(rs)}</td>"
                    f"<td class=m>{' · '.join(game_q) or '—'}</td><td class=m>{' · '.join(h2_q) or '—'}</td></tr>")
    frows = [f"<tr><td>{r['away']} @ {r['home']}</td><td>{r['away_final']}–{r['home_final']}</td>"
             f"<td class=m>{r.get('away_q')} / {r.get('home_q')}</td></tr>" for r in finals]
    grows = [f"<tr><td>{g['away']} @ {g['home']}</td><td>{g['status']}</td><td>{g['detail']}</td></tr>" for g in games]
    ts = datetime.now(timezone.utc).strftime("%b %d, %H:%M:%S UTC")
    html = f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=60>
<title>WNBA Tracker</title><style>
body{{font-family:system-ui,sans-serif;background:#F6F7F5;color:#20241F;max-width:760px;margin:40px auto;padding:0 20px}}
@media(prefers-color-scheme:dark){{body{{background:#151816;color:#E7EAE5}}th,td{{border-color:#2C312C!important}}}}
h1{{font-size:22px}} .live{{color:#1F8A5D;font-weight:600}}
table{{border-collapse:collapse;width:100%;margin:12px 0 28px;font-size:14px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #E2E5E0}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.6}}
.m{{font-family:Menlo,monospace;font-size:12.5px}} .sub{{opacity:.6;font-size:13px}}
</style>
<h1>WNBA halftime tracker <span class=live>●</span> <span class=sub>(cloud)</span></h1>
<p class=sub>Last pass: {ts} · snapshots {len(snaps)} · finals {len(finals)}</p>
<h3>Today's games</h3>
<table><tr><th>Game</th><th>Status</th><th>Detail</th></tr>{''.join(grows) or '<tr><td colspan=3>none today</td></tr>'}</table>
<h3>Halftime snapshots (latest per game — Kalshi yes bid/ask)</h3>
<table><tr><th>Game</th><th>Half score</th><th>Home spread</th><th>#snaps</th><th>Game winner</th><th>2H winner</th></tr>
{''.join(rows) or '<tr><td colspan=6>none yet</td></tr>'}</table>
<h3>Finals logged</h3>
<table><tr><th>Game</th><th>Final</th><th>Quarters (away / home)</th></tr>
{''.join(frows) or '<tr><td colspan=3>none yet</td></tr>'}</table>
"""
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS, "w") as f:
        f.write(html)


def run_once():
    """One polling pass. Returns summary of today's games for the caller."""
    now = datetime.now(timezone.utc).isoformat()
    sess = requests.Session()
    r = sess.get("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard", timeout=20)
    r.raise_for_status()
    events = r.json().get("events", [])
    summaries = []
    logged_finals = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            rec = json.loads(line)
            if rec.get("type") == "final":
                logged_finals.add(rec["espn_id"])
    km_game = km_2h = None
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as out:
        for ev in events:
            comp = ev["competitions"][0]
            status = ev["status"]["type"]["name"]
            eid = ev["id"]
            teams = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = teams["home"]["team"]["abbreviation"], teams["away"]["team"]["abbreviation"]
            summaries.append({"away": away, "home": home, "status": status.replace("STATUS_", ""),
                              "detail": ev["status"]["type"].get("shortDetail", "")})
            kh, ka = E2K.get(home, home), E2K.get(away, away)

            if status == "STATUS_HALFTIME":
                if km_game is None:
                    km_game = kalshi_tickers(sess, "KXWNBAGAME")
                    km_2h = kalshi_tickers(sess, "KXWNBA2HWINNER")
                ev_body = None
                for t in km_game:
                    body = t.split("-")[1]
                    if body[7:] in (ka + kh, kh + ka):
                        ev_body = body
                        break
                rec = {"type": "halftime_snapshot", "ts": now, "espn_id": eid,
                       "away": away, "home": home,
                       "away_h1": int(teams["away"]["score"]), "home_h1": int(teams["home"]["score"]),
                       "spread_home": pregame_spread(sess, eid), "kalshi": {}}
                if ev_body:
                    for series, km in (("KXWNBAGAME", km_game), ("KXWNBA2HWINNER", km_2h)):
                        for code in (kh, ka, "TIE"):
                            t = f"{series}-{ev_body}-{code}"
                            if t in km:
                                ob = orderbook(sess, t)
                                if ob:
                                    rec["kalshi"][t] = ob
                out.write(json.dumps(rec) + "\n")
                print(f"halftime snapshot: {away} @ {home} {rec['away_h1']}-{rec['home_h1']}", flush=True)

            elif status == "STATUS_FINAL" and eid not in logged_finals:
                def q(side):
                    return [int(float(x["value"])) for x in teams[side].get("linescores", [])
                            if x.get("value") is not None]
                rec = {"type": "final", "ts": now, "espn_id": eid, "away": away, "home": home,
                       "away_final": int(teams["away"]["score"]), "home_final": int(teams["home"]["score"]),
                       "away_q": q("away"), "home_q": q("home"), "spread_home": pregame_spread(sess, eid)}
                out.write(json.dumps(rec) + "\n")
                print(f"final logged: {away} @ {home} {rec['away_final']}-{rec['home_final']}", flush=True)
    render_status(summaries)
    return summaries


if __name__ == "__main__":
    run_once()
