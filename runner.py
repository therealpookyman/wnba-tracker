"""Game-window loop for GitHub Actions: poll every 2 minutes, commit data
every ~10 minutes, exit early when no games are live or upcoming soon."""
import subprocess, sys, time
from datetime import datetime, timezone
import tracker

WINDOW_MIN = 55           # short windows + hourly crons: a skipped cron costs <1h
POLL_SEC = 120
COMMIT_EVERY = 5          # polls between commits

LIVE = {"HALFTIME", "IN_PROGRESS", "END_PERIOD", "DELAYED"}


def commit():
    subprocess.run(["git", "config", "user.name", "wnba-tracker-bot"], check=False)
    subprocess.run(["git", "config", "user.email", "bot@users.noreply.github.com"], check=False)
    subprocess.run(["git", "add", "data/"], check=False)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", "tracker: data update"], check=False)
    for _ in range(3):
        subprocess.run(["git", "pull", "--rebase"], check=False)
        if subprocess.run(["git", "push"]).returncode == 0:
            return
        time.sleep(5)


def upcoming_soon(games):
    """True if any game hasn't finished yet (scheduled today or live)."""
    return any(g["status"] != "FINAL" for g in games)


def main():
    start = time.time()
    polls = 0
    while (time.time() - start) < WINDOW_MIN * 60:
        try:
            games = tracker.run_once()
        except Exception as e:
            print(f"pass error: {e}", flush=True)
            games = None
        polls += 1
        if polls % COMMIT_EVERY == 0:
            commit()
        if games is not None and not upcoming_soon(games):
            print("no live or upcoming games — exiting window early", flush=True)
            break
        if polls == 1 and games == []:
            print("no games today — exiting", flush=True)
            break
        time.sleep(POLL_SEC)
    commit()
    print(f"window done: {polls} polls, {datetime.now(timezone.utc).isoformat()}", flush=True)


if __name__ == "__main__":
    main()
