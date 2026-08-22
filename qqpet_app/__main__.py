from __future__ import annotations

import argparse
from pathlib import Path

from .paths import config_path, progress_path
from .scheduler import Scheduler


def main() -> None:
    parser = argparse.ArgumentParser(description="QQ 宠物接口调度器")
    parser.add_argument("--once", action="store_true", help="只运行一轮")
    parser.add_argument("--config", default=str(config_path()))
    parser.add_argument("--progress", default=str(progress_path()))
    args = parser.parse_args()
    scheduler = Scheduler(Path(args.config), Path(args.progress))
    if args.once:
        scheduler.run_once()
    else:
        try:
            scheduler.run_forever()
        except KeyboardInterrupt:
            scheduler.stop()


if __name__ == "__main__":
    main()
