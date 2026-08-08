"""``python -m pixelforge`` — GUI by default, CLI with ``--cli``."""

from __future__ import annotations

import sys


def main() -> int:
    if "--cli" in sys.argv:
        from .cli import main as cli_main

        argv = [a for a in sys.argv if a != "--cli"]
        return cli_main(argv[1:])

    from .app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
