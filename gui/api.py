"""FastAPI application for the gprmax Simulation Skill GUI.

All routes delegate to the shared ``scripts.*`` modules — no core logic is
duplicated here.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.staticfiles import StaticFiles
import yaml

from scripts import axes, templates_lib, wizard as wizard_mod
from scripts.probe_environment import collect_probe, format_report, probe_to_json
from scripts.research import identify_research_needs, render_needs

app = FastAPI(title="gprmax Simulation Skill", version="0.1.0")

# Serve the static frontend (index.html + app.js)
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# A default session directory in the system temp folder
DEFAULT_SESSION_DIR = Path(tempfile.gettempdir()) / "gprmax-skill-gui-sessions"


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main GUI page."""
    static = Path(__file__).resolve().parent / "static" / "index.html"
    return HTMLResponse(static.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Wizard (guided setup) endpoints
# --------------------------------------------------------------------------

@app.get("/api/wizard/fields")
async def wizard_fields():
    """Return the step definitions for the frontend to render the form."""
    return JSONResponse(wizard_mod.STEP_FIELDS)


@app.post("/api/wizard/init")
async def wizard_init():
    """Create a new wizard session."""
    DEFAULT_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    name = str(len(list(DEFAULT_SESSION_DIR.iterdir())))
    session = wizard_mod.create_session(DEFAULT_SESSION_DIR / name, force=True)
    return {"session_dir": str(session.path), "status": wizard_mod.status(session)}


@app.post("/api/wizard/answer")
async def wizard_answer(body: dict[str, Any]):
    """Record an answer for a field."""
    session_dir = Path(body["session_dir"])
    field = body["field"]
    value = body["value"]
    try:
        session = wizard_mod.load_session(session_dir)
        wizard_mod.answer(session, field, value)
    except (wizard_mod.WizardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"field": field, "answered": True, "status": wizard_mod.status(session)}


@app.get("/api/wizard/status")
async def wizard_status(session_dir: str):
    """Return the current session status."""
    try:
        session = wizard_mod.load_session(Path(session_dir))
    except wizard_mod.WizardError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return wizard_mod.status(session)


@app.post("/api/wizard/dump")
async def wizard_dump(body: dict[str, Any]):
    """Dump the session (answers, recommendations, numerics, contract draft)."""
    session_dir = Path(body["session_dir"])
    try:
        session = wizard_mod.load_session(session_dir)
        payload = wizard_mod.dump(session)
    except (wizard_mod.WizardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return payload


# --------------------------------------------------------------------------
# Axes (configuration axis recommendations)
# --------------------------------------------------------------------------

@app.post("/api/axes/recommend")
async def axes_recommend(body: dict[str, Any]):
    """Return per-axis recommendations based on scenario and fidelity."""
    try:
        rec = axes.recommend(
            scenario=body.get("scenario", "other"),
            fidelity=body.get("fidelity", "standard"),
            explicit=body.get("explicit"),
            needs_sfcw=body.get("needs_sfcw"),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return rec


# --------------------------------------------------------------------------
# Environment probe
# --------------------------------------------------------------------------

@app.post("/api/probe")
async def probe():
    """Probe the local environment and return structured report."""
    probe_data = collect_probe()
    return {
        "data": probe_data,
        "text_report": format_report(probe_data),
    }


# --------------------------------------------------------------------------
# Template library
# --------------------------------------------------------------------------

@app.post("/api/template/match")
async def template_match(body: dict[str, Any]):
    """Strict-match a study signature against verified scene templates."""
    scenarios_dir = Path(body.get("scenarios_dir", "templates/scenarios"))
    signature = body.get("signature", {})
    try:
        matched = templates_lib.match_scenario(signature, scenarios_dir)
    except templates_lib.TemplateError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"matched": matched is not None, "template": matched}


# --------------------------------------------------------------------------
# Research needs
# --------------------------------------------------------------------------

@app.post("/api/research/needs")
async def research_needs(body: dict[str, Any]):
    """Identify research needs from a contract draft."""
    contract = body.get("contract", {})
    materials_dir = Path(body.get("materials_dir", "materials"))
    scenarios_dir = Path(body.get("scenarios_dir", "templates/scenarios"))
    try:
        needs = identify_research_needs(
            contract, materials_dir=materials_dir, scenarios_dir=scenarios_dir
        )
    except (ValueError, templates_lib.TemplateError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {
        "needs": [n.to_dict() for n in needs],
        "text": render_needs(needs),
    }