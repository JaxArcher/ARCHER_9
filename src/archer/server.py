"""
ARCHER Mobile API Server
FastAPI wrapper around existing agent orchestrator for mobile app access.
"""

import os
import json
import logging
import datetime
from typing import Optional, List, Dict, Any, Generator

from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from archer.agents.orchestrator import AgentOrchestrator
from archer.config import get_config
from archer.core.event_bus import get_event_bus, Event, EventType

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("archer-server")

app = FastAPI(title="ARCHER Mobile API", version="1.0.0")

# CORS - only allow Tailscale network (open by default, restrict via config if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production to Tailscale IPs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication
# In production, this should be a strong random token stored in .env
MOBILE_TOKEN = os.getenv("ARCHER_MOBILE_TOKEN", "CHANGE_IN_PRODUCTION")

def verify_token(authorization: str = Header(...)):
    """Verify bearer token from mobile app."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    if token != MOBILE_TOKEN:
        logger.warning(f"Invalid token attempt: {token[:4]}...")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return token


# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    user_id: str = "col"
    response_format: str = "text"  # "text" or "audio"


class ChatResponse(BaseModel):
    agent: str
    response: str
    timestamp: str
    conversation_id: str


# Global orchestrator / agent instance (singleton)
_orchestrator = None

def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from archer.agents.core_agent import CoreAgent
        _orchestrator = CoreAgent()
    return _orchestrator

def set_orchestrator(orch: Any):
    """Inject a pre-initialized agent or orchestrator instance."""
    global _orchestrator
    _orchestrator = orch


# Endpoints
@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "ARCHER Mobile API"}


@app.get("/mobile/health")
async def health_check():
    """Detailed health check - no authentication required."""
    orch = get_orchestrator()
    return {
        "status": "healthy",
        "version": "1.0.0",
        "active_agent": orch.active_agent,
        "session_id": orch.session_id,
        "agents_available": [
            "assistant", "trainer", "therapist", "investment",
            "blindspot", "inventory", "observer"
        ]
    }


@app.post("/mobile/chat", response_model=ChatResponse)
async def mobile_chat(
    request: ChatRequest,
    token: str = Depends(verify_token)
):
    """
    Process text message from mobile app and return agent response.
    Blocks until full response is generated (for simple mobile clients).
    """
    orch = get_orchestrator()
    
    try:
        # Orchestrator handles memory storage internally
        response_text = orch.process_request(request.message)
        
        return ChatResponse(
            agent=orch.active_agent.capitalize(),
            response=response_text,
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            conversation_id=orch.session_id
        )
    except Exception as e:
        logger.error(f"Mobile chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mobile/stream")
async def mobile_stream(
    request: ChatRequest,
    token: str = Depends(verify_token)
):
    """
    Sentence-level streaming for lower latency in mobile UI.
    Returns NDJSON stream.
    """
    orch = get_orchestrator()
    
    def generate() -> Generator[str, None, None]:
        try:
            for sentence in orch.process_request_streaming(request.message):
                yield json.dumps({
                    "sentence": sentence,
                    "agent": orch.active_agent,
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                }) + "\n"
        except Exception as e:
            logger.error(f"Mobile streaming error: {e}")
            yield json.dumps({"error": str(e)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/mobile/memory/recent")
async def get_recent_memory(
    limit: int = 20,
    token: str = Depends(verify_token)
):
    """
    Get recent conversations from memory.
    """
    orch = get_orchestrator()
    try:
        # Access the underlying history from orchestrator
        with orch._history_lock:
            history = list(orch._conversation_history[-limit:])
        
        return {
            "conversations": history,
            "total": len(history),
            "session_id": orch.session_id
        }
    except Exception as e:
        logger.error(f"Memory access error: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve memory.")


@app.get("/mobile/memory/search")
async def search_memory(
    q: str,
    limit: int = 10,
    token: str = Depends(verify_token)
):
    """
    Semantic search across conversation memory.
    """
    orch = get_orchestrator()
    try:
        # We need to access the ChromaDB store. 
        # In a real implementation, we'd query the store directly.
        # For now, we search within the loaded context if possible, 
        # but full semantic search requires reaching into the memory agent.
        
        results = orch._retrieve_memory_context(q, limit=limit)
        
        return {
            "results": results,
            "query": q,
            "total_results": len(results)
        }
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail="Search failed.")


def start_server(host: str = None, port: int = None):
    config = get_config()
    host = host or config.api_host
    port = port or config.api_port
    logger.info(f"Starting ARCHER Mobile API on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
