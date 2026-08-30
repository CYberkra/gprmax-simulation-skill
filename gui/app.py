"""Entry point for the gprmax Simulation Skill GUI.

Run with::

    python -m gui.app

Then open http://127.0.0.1:8123 in a browser.
"""

from __future__ import annotations


def main() -> None:  # pragma: no cover
    import uvicorn

    from gui.api import app

    uvicorn.run(app, host="127.0.0.1", port=8123, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()