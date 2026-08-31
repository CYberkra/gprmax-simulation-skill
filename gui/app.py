"""Entry point for the gprmax Simulation Skill GUI.

Run with::

    python -m gui.app

Then open http://127.0.0.1:8123 in a browser (override with the
``GPRMAX_SKILL_PORT`` environment variable).
"""

from __future__ import annotations

import os


def _port() -> int:
    return int(os.environ.get("GPRMAX_SKILL_PORT", "8123"))


def main() -> None:  # pragma: no cover
    import uvicorn

    from gui.api import app

    uvicorn.run(app, host="127.0.0.1", port=_port(), reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
