"""
FastAPI server: serves the HTML UI and proxies requests to the ADK agent session.
"""
import os
import sys
import uuid
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agent import root_agent
from tools.classify_symptom import classify_symptom
from tools.recommend_provider import recommend_provider

app = FastAPI(title="Estimador Agéntico de Copago y Cobertura")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ─── ADK session setup ────────────────────────────────────────────────────────

session_service = InMemorySessionService()
APP_NAME = "estimador_copago"

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)

# In-memory store: session_id → {symptom_text, specialty, attention_type, urgency}
_session_state: dict[str, dict] = {}


# ─── Request/Response models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class EstimateRequest(BaseModel):
    session_id: str
    insurer_id: str
    plan_id: str
    deductible_remaining_usd: float


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    # Ensure ADK session exists
    existing = await session_service.get_session(app_name=APP_NAME, user_id="user", session_id=session_id)
    if not existing:
        await session_service.create_session(app_name=APP_NAME, user_id="user", session_id=session_id)

    # Run the agent
    user_message = Content(role="user", parts=[Part(text=req.message)])
    reply_text = ""
    async for event in runner.run_async(
        user_id="user",
        session_id=session_id,
        new_message=user_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            reply_text = event.content.parts[0].text or ""

    # Quick keyword triage to decide if we should show the insurance form
    classify_result = classify_symptom(req.message)
    _session_state[session_id] = {
        "specialty": classify_result["specialty"],
        "attention_type": classify_result["attention_type"],
        "urgency": classify_result["urgency"],
        "red_flags": classify_result["red_flags"],
    }

    show_form = bool(classify_result["specialty"])

    return JSONResponse({
        "session_id": session_id,
        "reply": reply_text,
        "show_insurance_form": show_form,
    })


@app.post("/estimate")
async def estimate(req: EstimateRequest):
    state = _session_state.get(req.session_id, {})
    specialty = state.get("specialty", "medicina_general")
    attention_type = state.get("attention_type", "consulta")
    urgency = state.get("urgency", "baja")

    result = recommend_provider(
        city="Quito",
        specialty=specialty,
        attention_type=attention_type,
        insurer_id=req.insurer_id,
        plan_id=req.plan_id,
        deductible_remaining_usd=req.deductible_remaining_usd,
    )

    if "error" in result:
        return JSONResponse({"error": result["error"]})

    providers = result.get("ranked_providers", [])
    best = result.get("best_option")

    # Build a human-readable summary for the chat
    if best:
        summary = (
            f"Con tu plan, la opción más conveniente es {best['display_name']} "
            f"con un gasto estimado de ${best['estimated_out_of_pocket_usd']}. "
            f"Revisa los 3 prestadores recomendados en el panel de resultados."
        )
    else:
        summary = "No encontré prestadores compatibles para tu búsqueda en Quito."

    return JSONResponse({
        "specialty": specialty,
        "attention_type": attention_type,
        "urgency": urgency,
        "providers": providers,
        "agent_summary": summary,
    })


# Mount static files last so routes take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
