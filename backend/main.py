"""
FastAPI Application for TBX Finance Assistant
Main entry point with endpoints for chat, session management, exports
"""

import os
import logging
from typing import Optional, Dict, Any, List
import uuid
from datetime import datetime
import json

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio

from langgraph_flow import build_finance_graph, FinanceAssistantState
from tools import ContextManager, DataExporter
from database import get_db

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

FASTAPI_HOST = os.getenv("FASTAPI_HOST", "localhost")
FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", 8000))
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT_MINUTES", 60))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.60))

# ============================================================================
# MODELS
# ============================================================================

class ChatMessage(BaseModel):
    content: str
    role: str = "user"

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: ChatMessage
    model: str = "qwen2.5-coder-1.5b"

class ChatResponse(BaseModel):
    session_id: str
    message: str
    confidence_score: float
    confidence_band: str
    grounding_info: Dict[str, Any]
    anomalies_detected: List[Dict[str, Any]]
    query_results: List[Dict[str, Any]]
    export_available: bool
    export_filename: Optional[str] = None

class SessionInfo(BaseModel):
    session_id: str
    created_at: str
    messages_count: int
    last_message_at: str

class ExportRequest(BaseModel):
    session_id: str
    format: str = "csv"

# ============================================================================
# IN-MEMORY SESSION MANAGER (Redis removed for local/dev use; see PRODUCTION.md)
# ============================================================================

class SessionManager:
    """Manage sessions in-process. Conversation is stored as paired Q&A turns
    (not a flat message log) so context summarization has meaningful content to work with.
    Sessions are lost on process restart — use the Redis-backed version in production."""
    
    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.timeout = SESSION_TIMEOUT * 60  # Convert to seconds
    
    def create_session(self) -> str:
        """Create new session"""
        session_id = str(uuid.uuid4())
        now = datetime.now()
        self._sessions[session_id] = {
            "created_at": now.isoformat(),
            "messages": [],
            "last_message_at": now.isoformat(),
            "_expires_at": now.timestamp() + self.timeout
        }
        
        logger.info(f"Session created: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data"""
        session = self._sessions.get(session_id)
        if not session:
            return None
        
        if datetime.now().timestamp() > session["_expires_at"]:
            del self._sessions[session_id]
            return None
        
        return session
    
    def add_turn(self, session_id: str, question: str, answer: str,
                export_filename: Optional[str] = None):
        """Store one Q&A turn (question+answer together) rather than two separate messages"""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        session["messages"].append({
            "question": question,
            "answer": answer,
            "export_filename": export_filename,
            "timestamp": datetime.now().isoformat()
        })
        
        now = datetime.now()
        session["last_message_at"] = now.isoformat()
        session["_expires_at"] = now.timestamp() + self.timeout
    
    def get_context(self, session_id: str, max_turns: int = 3) -> List[Dict]:
        """Get compressed conversation context (last N full turns + summaries of older ones)"""
        session = self.get_session(session_id)
        if not session:
            return []
        
        return ContextManager.compress_context(session["messages"], max_turns)

    def get_last_export_filename(self, session_id: str) -> Optional[str]:
        """Find the most recent turn in this session that produced a CSV export"""
        session = self.get_session(session_id)
        if not session:
            return None
        
        for turn in reversed(session["messages"]):
            if turn.get("export_filename"):
                return turn["export_filename"]
        return None

    def list_sessions(self) -> List[Dict]:
        """List all live (non-expired) sessions, newest activity first, for the sidebar"""
        now = datetime.now().timestamp()
        expired = [sid for sid, s in self._sessions.items() if now > s["_expires_at"]]
        for sid in expired:
            del self._sessions[sid]
        
        summaries = []
        for session_id, session in self._sessions.items():
            first_question = session["messages"][0]["question"] if session["messages"] else None
            summaries.append({
                "session_id": session_id,
                "created_at": session["created_at"],
                "last_message_at": session["last_message_at"],
                "messages_count": len(session["messages"]),
                "preview": first_question
            })
        
        summaries.sort(key=lambda s: s["last_message_at"], reverse=True)
        return summaries

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="TBX Finance Assistant",
    description="Conversational AI for financial data queries",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

session_manager = SessionManager()

# Build LangGraph
try:
    finance_graph = build_finance_graph()
    logger.info("LangGraph built successfully")
except Exception as e:
    logger.error(f"Failed to build LangGraph: {e}")
    finance_graph = None

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "session_backend": "in-memory",
        "database_initialized": True
    }

@app.post("/sessions/create", response_model=Dict[str, str])
async def create_session():
    """Create new chat session"""
    try:
        if not session_manager:
            raise HTTPException(status_code=500, detail="Session service unavailable")
        
        session_id = session_manager.create_session()
        
        return {
            "session_id": session_id,
            "message": "Session created successfully"
        }
    
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions", response_model=List[Dict[str, Any]])
async def list_sessions():
    """List all active sessions for the sidebar, most recently active first"""
    try:
        if not session_manager:
            raise HTTPException(status_code=500, detail="Session service unavailable")
        
        return session_manager.list_sessions()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """Get session information"""
    try:
        if not session_manager:
            raise HTTPException(status_code=500, detail="Session service unavailable")
        
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return SessionInfo(
            session_id=session_id,
            created_at=session["created_at"],
            messages_count=len(session["messages"]),
            last_message_at=session.get("last_message_at", "")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions/{session_id}/messages", response_model=List[Dict[str, Any]])
async def get_session_messages(session_id: str):
    """Get this session's Q&A turns flattened into chat messages, to rehydrate the UI"""
    try:
        if not session_manager:
            raise HTTPException(status_code=500, detail="Session service unavailable")
        
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        chat_messages = []
        for turn in session["messages"]:
            chat_messages.append({"role": "user", "content": turn["question"]})
            chat_messages.append({"role": "assistant", "content": turn["answer"]})
        
        return chat_messages
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process chat message and return response"""
    try:
        # Validate inputs
        if not finance_graph:
            raise HTTPException(status_code=500, detail="Assistant service unavailable")
        
        if not request.session_id:
            request.session_id = session_manager.create_session()
        
        # Get or verify session exists
        if not session_manager.get_session(request.session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        
        logger.info(f"Processing query: {request.message.content[:100]}")
        
        # Initialize state
        state = FinanceAssistantState(
            user_query=request.message.content,
            model_used=request.model
        )
        
        # Get conversation context
        context = session_manager.get_context(request.session_id)
        state.conversation_history = context
        
        # Run through LangGraph (nodes are async, so use ainvoke)
        try:
            result = await finance_graph.ainvoke(state.dict())
            
            # Convert result back to state
            if isinstance(result, dict):
                response_state = FinanceAssistantState(**result)
            else:
                response_state = result
        
        except Exception as e:
            logger.error(f"LangGraph execution error: {e}")
            response_state = FinanceAssistantState(
                user_query=request.message.content,
                execution_error=str(e),
                final_answer=f"Error processing query: {str(e)}"
            )
        
        # Save turn to session (question + answer stored together, so summarization works)
        session_manager.add_turn(
            request.session_id,
            request.message.content,
            response_state.final_answer,
            response_state.export_filename,
        )
        
        # Confidence: use the composite value already computed in response_formatting_node
        # (avoids recomputing with a different, drift-prone formula here)
        confidence = response_state.composite_confidence or response_state.confidence_score
        if confidence >= 0.8:
            confidence_band = "high"
        elif confidence >= CONFIDENCE_THRESHOLD:
            confidence_band = "medium"
        else:
            confidence_band = "low"
        
        return ChatResponse(
            session_id=request.session_id,
            message=response_state.final_answer,
            confidence_score=confidence,
            confidence_band=confidence_band,
            grounding_info=response_state.grounding_info,
            anomalies_detected=response_state.anomalies,
            query_results=response_state.query_results,
            export_available=len(response_state.query_results) > 0,
            export_filename=response_state.export_filename
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/export")
async def export_data(request: ExportRequest):
    """Export session query results as a downloadable CSV"""
    try:
        if not session_manager:
            raise HTTPException(status_code=500, detail="Export service unavailable")
        
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        filename = session_manager.get_last_export_filename(request.session_id)
        if not filename or not os.path.exists(filename):
            raise HTTPException(status_code=404, detail="No export available for this session yet")
        
        return FileResponse(
            path=filename,
            media_type="text/csv",
            filename=os.path.basename(filename),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/schema")
async def get_schema():
    """Get database schema information"""
    try:
        db = get_db()
        schema = db.get_schema_info()
        
        return {
            "schema": schema,
            "tables": list(schema.keys())
        }
    
    except Exception as e:
        logger.error(f"Schema endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("TBX Finance Assistant starting...")
    
    try:
        # Initialize database
        db = get_db()
        logger.info("Database initialized")
        
        # Sanity-check session manager
        if session_manager:
            test_session = session_manager.create_session()
            logger.info(f"Session manager ready, test session: {test_session}")
        
        logger.info("Application startup complete")
    
    except Exception as e:
        logger.error(f"Startup error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("TBX Finance Assistant shutting down...")
    
    try:
        db = get_db()
        if db:
            db.close()
        
        logger.info("Shutdown complete")
    
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=FASTAPI_HOST,
        port=FASTAPI_PORT,
        reload=os.getenv("DEBUG_MODE", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
