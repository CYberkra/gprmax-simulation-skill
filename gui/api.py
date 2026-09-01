"""FastAPI application for the gprmax Simulation Skill GUI.

All routes delegate to the shared ``scripts.*`` modules — no core logic is
duplicated here.
"""

from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import yaml

from scripts import axes, templates_lib, wizard as wizard_mod
from scripts import batch as batch_mod
from scripts import diagnose as diagnose_mod
from scripts import report as report_mod
from scripts import sensitivity as sensitivity_mod
from scripts import sketch as sketch_mod
from scripts import visualize as visualize_mod
from scripts import scaffold as scaffold_mod
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
    """Create a new wizard session with a collision-free name."""
    DEFAULT_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    name = f"session_{int(time.time() * 1000)}"
    session = wizard_mod.create_session(DEFAULT_SESSION_DIR / name)
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
    except (ValueError, KeyError) as error:
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

# --------------------------------------------------------------------------
# Geometry sketch
# --------------------------------------------------------------------------

@app.post("/api/sketch")
async def geometry_sketch(body: dict[str, Any]):
    """Render a geometry cross-section sketch from a contract."""
    contract = body.get("contract", {})
    try:
        import base64

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sketch.png"
            sketch_mod.plot_geometry_sketch(contract, out)
            png_b64 = base64.b64encode(out.read_bytes()).decode("ascii")
    except (sketch_mod.SketchError, ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"png_b64": png_b64}


# --------------------------------------------------------------------------
# Numerical diagnostics
# --------------------------------------------------------------------------

@app.post("/api/diagnose")
async def diagnose(body: dict[str, Any]):
    """Run pre-run diagnostics on a contract."""
    contract = body.get("contract", {})
    gpu_vram_gb = body.get("gpu_vram_gb")
    try:
        findings = diagnose_mod.diagnose_model(
            contract, gpu_vram_gb=gpu_vram_gb
        )
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {
        "findings": [f.to_dict() for f in findings],
        "text": diagnose_mod.render_diagnostics(findings),
    }


# --------------------------------------------------------------------------
# Parameter sensitivity
# --------------------------------------------------------------------------

@app.post("/api/sensitivity")
async def sensitivity(body: dict[str, Any]):
    """Run parameter sensitivity analysis on a contract."""
    contract = body.get("contract", {})
    perturbation = body.get("perturbation", 0.2)
    try:
        results = sensitivity_mod.analyse_sensitivity(
            contract, perturbation=perturbation
        )
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {
        "results": [r.to_dict() for r in results],
        "text": sensitivity_mod.render_sensitivity(results),
    }


# --------------------------------------------------------------------------
# Model-card report
# --------------------------------------------------------------------------

@app.post("/api/report")
async def model_card(body: dict[str, Any]):
    """Render a model-card Markdown report from a contract."""
    contract = body.get("contract", {})
    try:
        markdown = report_mod.render_model_card(contract)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"markdown": markdown}


# --------------------------------------------------------------------------
# Study directory operations
# --------------------------------------------------------------------------

@app.post("/api/study/init")
async def study_init(body: dict[str, Any]):
    """Create the standard study skeleton."""
    path = Path(body.get("path", "study"))
    name = body.get("name")
    try:
        created = scaffold_mod.create_study_skeleton(path, name=name)
    except (scaffold_mod.ScaffoldError, ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"created": [str(p) for p in created]}


@app.post("/api/study/audit")
async def study_audit(body: dict[str, Any]):
    """Audit a study directory against the layout discipline."""
    path = Path(body.get("path", "study"))
    try:
        findings = scaffold_mod.audit_layout(path)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"findings": findings}


@app.post("/api/study/hash")
async def study_hash(body: dict[str, Any]):
    """Record SHA-256 of outputs/ into manifest.json."""
    path = Path(body.get("path", "study"))
    try:
        manifest = scaffold_mod.record_output_hashes(path)
        hashes = scaffold_mod.output_hashes(path)
    except (scaffold_mod.ScaffoldError, ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"count": len(hashes), "manifest": str(manifest)}


@app.post("/api/study/check")
async def study_check(body: dict[str, Any]):
    """Check whether the model is established (single-model-before-batch gate)."""
    path = Path(body.get("path", "study"))
    try:
        gaps = batch_mod.model_establishment_gaps(path)
    except (batch_mod.BatchError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"established": not gaps, "gaps": gaps}


# --------------------------------------------------------------------------
# SFCW processing (A-scan / B-scan visualisation)
# --------------------------------------------------------------------------

@app.post("/api/process")
async def process_output(body: dict[str, Any]):
    """Process a gprMax .out into an A-scan PNG.

    For ``impulse_lti`` the receiver Ez trace is used as the impulse response
    (h[n]) when no ``impulse_response`` path is supplied — a single-trace
    convenience that matches the CLI's demo route.
    """
    out_path = Path(body.get("out_path", ""))
    if not out_path.is_file():
        raise HTTPException(status_code=422, detail=f"{out_path} is not a file")
    mode = body.get("mode", "impulse_lti")
    band = body.get("band", "200-350")
    impulse_response = None
    if body.get("impulse_response"):
        impulse_response = np.load(body["impulse_response"])
    elif mode == "impulse_lti":
        impulse_response = visualize_mod.read_ez_from_out(out_path)[0][0]
    try:
        lo_str, hi_str = str(band).split("-")
        f_lo, f_hi = float(lo_str), float(hi_str)
        df = float(body.get("df_mhz", 50))
        frequencies_mhz = [f_lo + i * df for i in range(int(round((f_hi - f_lo) / df)) + 1)]
        import base64

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            artifacts = visualize_mod.process_and_plot(
                out_path,
                mode=mode,
                frequencies_mhz=frequencies_mhz,
                output_dir=out_dir,
                impulse_response=impulse_response,
            )
            png_b64 = base64.b64encode(
                artifacts["ascan_png"].read_bytes()
            ).decode("ascii")
            params = artifacts["parameters_json"].read_text(encoding="utf-8")
    except (
        visualize_mod.ProcessingError,
        ValueError,
        OSError,
        IndexError,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"png_b64": png_b64, "params_json": params}
