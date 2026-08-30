"""GUI application for the gprmax Simulation Skill.

FastAPI-based local web UI.  Run with::

    python -m gui.app

Or, after installing the skill with the ``gui`` extra::

    gprmax-skill-gui
"""

from __future__ import annotations

if __name__ == "__main__":  # pragma: no cover
    from gui.app import main

    main()