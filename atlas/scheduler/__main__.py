"""L8 Scheduler CLI — for system cron / launchd or manual use.

    python -m atlas.scheduler list            # show jobs + next/last run
    python -m atlas.scheduler run-due          # run everything currently due (cron entry)
    python -m atlas.scheduler run <job_id>     # force-run one job now
    python -m atlas.scheduler start            # run the blocking loop in foreground

On the Mac, a single launchd/cron line calling `run-due` each minute is all the
OS integration ATLAS needs; the in-process thread (server) is the alternative.
"""
from __future__ import annotations

import sys

from .scheduler import Scheduler


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "list"
    sched = Scheduler()

    if cmd == "list":
        for j in sched.status():
            print(f"{j['id']:16} next={j['next_run']}  last={j['last_run']}  "
                  f"status={j['last_status']}  ({j['risk']})")
        return 0
    if cmd == "run-due":
        ran = sched.run_due()
        print("ran:", ", ".join(ran) if ran else "(nothing due)")
        return 0
    if cmd == "run" and len(argv) > 1:
        try:
            st = sched.run_now(argv[1])
        except KeyError:
            print(f"no such job: {argv[1]}", file=sys.stderr)
            return 2
        print(f"{argv[1]}: {st['last_status']} — {st['last_result']}")
        return 0
    if cmd == "start":
        import time
        sched.start()
        print("scheduler loop started (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sched.stop()
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
