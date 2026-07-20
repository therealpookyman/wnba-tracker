# wnba-tracker

Logs WNBA halftime state + Kalshi orderbook snapshots (game winner and
2nd-half winner markets) for every game, via public ESPN and Kalshi APIs.
Runs in GitHub Actions during game windows; data commits to `data/`.

Part of a study on how live prediction markets price pregame favorites that
trail at halftime.

- `tracker.py` — one polling pass (also runnable locally)
- `runner.py` — game-window loop used by the workflow
- `data/wnba_tracking.jsonl` — halftime snapshots + finals
- `data/wnba_status.html` — human-readable status page
