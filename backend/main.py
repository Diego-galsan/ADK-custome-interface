from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import json
import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Any
import logging
import httpx

from models import AgentRunRequest, Session, EvalCase, EvalSet, LiveRequest, Artifact

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ADK Backend", version="1.0.0")

# Configuration for remote agent
REMOTE_AGENT_URL = "http://localhost:8080"

@app.put("/config/agent-url")
async def update_agent_url(config: dict):
    """Update the remote agent URL"""
    global REMOTE_AGENT_URL
    new_url = config.get("url", "")
    if new_url:
        REMOTE_AGENT_URL = new_url
        logger.info(f"Updated remote agent URL to: {REMOTE_AGENT_URL}")
        return {"status": "updated", "remote_agent_url": REMOTE_AGENT_URL}
    else:
        raise HTTPException(status_code=400, detail="URL is required")

@app.get("/config/agent-url")
async def get_agent_url():
    """Get the current remote agent URL"""
    return {"remote_agent_url": REMOTE_AGENT_URL}

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],  # Angular dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (replace with database in production)
sessions: Dict[str, Session] = {}
eval_sets: Dict[str, EvalSet] = {}
apps: List[str] = ["sample-app", "demo-agent", "test-application"]
artifacts: Dict[str, Artifact] = {}

# WebSocket connections
websocket_connections: List[WebSocket] = []

@app.get("/")
async def root():
    return {"message": "ADK Backend Server", "status": "running", "remote_agent": REMOTE_AGENT_URL}

@app.post("/test-agent")
async def test_agent_connection(message: dict = None):
    """Test endpoint to verify communication with remote agent"""
    
    if message is None:
        message = {"text": "What can you do?"}
    
    try:
        # Prepare request for remote agent
        agent_request = {
            "id": "msg-test-connection",
            "params": {
                "message": {
                    "messageId": "msg-test-connection",
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": message.get("text", "Hello, can you hear me?")
                        }
                    ],
                    "contextId": "context-test"
                }
            }
        }
        
        logger.info(f"Testing connection to remote agent at {REMOTE_AGENT_URL}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                REMOTE_AGENT_URL,
                json=agent_request,
                headers={"Content-Type": "application/json"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                agent_response = response.json()
                return {
                    "status": "success",
                    "remote_agent_url": REMOTE_AGENT_URL,
                    "request": agent_request,
                    "response": agent_response
                }
            else:
                return {
                    "status": "error",
                    "remote_agent_url": REMOTE_AGENT_URL,
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
                
    except httpx.RequestError as e:
        return {
            "status": "error",
            "remote_agent_url": REMOTE_AGENT_URL,
            "error": f"Connection error: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error", 
            "remote_agent_url": REMOTE_AGENT_URL,
            "error": f"Unexpected error: {str(e)}"
        }

# Agent endpoints
@app.get("/list-apps")
async def list_apps(relative_path: str = "./"):
    """List available applications"""
    return apps

@app.get("/test-sse")
async def test_sse():
    """Test SSE endpoint to verify streaming works"""
    async def generate_test_sse():
        test_response = {
            "id": "test-123",
            "author": "model",
            "content": {
                "parts": [
                    {
                        "text": "This is a test message to verify SSE works"
                    }
                ]
            }
        }
        logger.info(f"Sending test SSE: {test_response}")
        yield f"data: {json.dumps(test_response)}\n\n"
    
    return EventSourceResponse(generate_test_sse())

@app.post("/run_sse")
async def run_sse(request: dict):
    """Server-sent events endpoint for streaming agent responses"""
    
    # Extract request data manually
    app_name = request.get("appName", "unknown")
    user_id = request.get("userId", "unknown")
    session_id = request.get("sessionId", "unknown")
    new_message = request.get("newMessage", {})
    
    async def generate_sse_response():
        try:
            # Get or create session
            if session_id not in sessions:
                # Create session if it doesn't exist
                session = Session(
                    id=session_id,
                    appName=app_name,
                    userId=user_id,
                    createdAt=datetime.now()
                )
                sessions[session_id] = session
                logger.info(f"Created new session {session_id} during message processing")
            
            current_session = sessions[session_id]
            
            # Store user message event
            user_event_id = str(uuid.uuid4())
            user_event = {
                "id": user_event_id,
                "timestamp": datetime.now().isoformat(),
                "type": "user_message",
                "role": "user",
                "content": new_message,
                "sessionId": session_id
            }
            current_session.events.append(user_event)
            
            # Prepare request for remote agent
            agent_request = {
                "id": f"msg-{uuid.uuid4()}",
                "params": {
                    "message": {
                        "messageId": f"msg-{uuid.uuid4()}",
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": new_message.get("parts", [{}])[0].get("text", "Hello") if new_message.get("parts") else new_message.get("text", "Hello")
                            }
                        ],
                        "contextId": f"context-{session_id}",
                        "sessionId": session_id  # Also include session ID directly
                    },
                    "sessionId": session_id,  # Include session ID at params level too
                    "appName": app_name,
                    "userId": user_id
                }
            }
            
            logger.info(f"Sending request to remote agent with session ID {session_id}: {agent_request}")
            
            # Send request to remote agent
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    REMOTE_AGENT_URL,
                    json=agent_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    agent_response = response.json()
                    logger.info(f"Received response from remote agent: {agent_response}")
                    
                    # Extract the actual text from the agent response
                    try:
                        # Try multiple response format patterns
                        agent_text = None
                        
                        # Pattern 1: result.artifacts[0].parts[0].text
                        result = agent_response.get("result", {})
                        artifacts = result.get("artifacts", [])
                        if artifacts and len(artifacts) > 0:
                            first_artifact = artifacts[0]
                            parts = first_artifact.get("parts", [])
                            if parts and len(parts) > 0:
                                agent_text = parts[0].get("text", None)
                        
                        # Pattern 2: Direct text in response
                        if not agent_text:
                            agent_text = agent_response.get("text", None)
                        
                        # Pattern 3: content.text
                        if not agent_text:
                            content = agent_response.get("content", {})
                            agent_text = content.get("text", None)
                        
                        # Pattern 4: message.content
                        if not agent_text:
                            message = agent_response.get("message", {})
                            agent_text = message.get("content", None)
                        
                        # Pattern 5: response field
                        if not agent_text:
                            agent_text = agent_response.get("response", None)
                        
                        # Fallback: convert whole response to string if no text found
                        if not agent_text:
                            agent_text = f"Received response but no text field found. Raw response: {json.dumps(agent_response)}"
                            
                        # Format response to match what the frontend expects
                        # The frontend expects: chunkJson.content.parts[].text
                        formatted_response = {
                            "id": str(uuid.uuid4()),
                            "author": "model",
                            "content": {
                                "parts": [
                                    {
                                        "text": agent_text
                                    }
                                ]
                            }
                        }
                        
                        logger.info(f"Sending formatted SSE response: {formatted_response}")
                        
                        # Store agent response event
                        agent_event_id = str(uuid.uuid4())
                        agent_event = {
                            "id": agent_event_id,
                            "timestamp": datetime.now().isoformat(),
                            "type": "agent_response",
                            "role": "assistant",
                            "content": formatted_response["content"],
                            "sessionId": session_id,
                            "rawResponse": agent_response  # Store the raw response for debugging
                        }
                        current_session.events.append(agent_event)
                        
                        # Update session state (simple example)
                        current_session.state = {
                            "lastActivity": datetime.now().isoformat(),
                            "messageCount": len(current_session.events),
                            "lastAgentResponse": agent_text[:100] + "..." if len(agent_text) > 100 else agent_text
                        }
                        
                        # EventSourceResponse will automatically add "data: " prefix
                        yield json.dumps(formatted_response)
                        
                    except Exception as parse_error:
                        logger.error(f"Error parsing agent response: {parse_error}")
                        # Fallback response
                        fallback_response = {
                            "id": str(uuid.uuid4()),
                            "author": "model", 
                            "content": {
                                "parts": [
                                    {
                                        "text": f"Error parsing response: {str(parse_error)}"
                                    }
                                ]
                            }
                        }
                        logger.info(f"Sending fallback SSE response: {fallback_response}")
                        yield json.dumps(fallback_response)
                else:
                    logger.error(f"Remote agent error: {response.status_code} - {response.text}")
                    error_response = {
                        "id": str(uuid.uuid4()),
                        "author": "model",
                        "content": {
                            "parts": [
                                {
                                    "text": f"Agent error: {response.status_code}"
                                }
                            ]
                        }
                    }
                    yield json.dumps(error_response)
                    
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to remote agent: {e}")
            # Fallback response
            fallback_response = {
                "id": str(uuid.uuid4()),
                "author": "model",
                "content": {
                    "parts": [
                        {
                            "text": "Could not connect to remote agent. Please check if the agent is running on port 8080."
                        }
                    ]
                }
            }
            yield json.dumps(fallback_response)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            error_response = {
                "id": str(uuid.uuid4()),
                "author": "model",
                "content": {
                    "parts": [
                        {
                            "text": f"Unexpected error: {str(e)}"
                        }
                    ]
                }
            }
            yield json.dumps(error_response)
    
    return EventSourceResponse(generate_sse_response())

# Session Management endpoints
@app.post("/apps/{app_name}/users/{user_id}/sessions")
async def create_session(app_name: str, user_id: str):
    """Create a new session"""
    session_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        appName=app_name,
        userId=user_id,
        createdAt=datetime.now()
    )
    sessions[session_id] = session
    logger.info(f"Created session {session_id} for user {user_id} in app {app_name}")
    return {"sessionId": session_id, "status": "created"}

@app.get("/apps/{app_name}/users/{user_id}/sessions")
async def list_sessions(app_name: str, user_id: str):
    """List all sessions for a user in an app"""
    user_sessions = [
        {
            "id": session.id,
            "appName": session.appName,
            "userId": session.userId,
            "createdAt": session.createdAt.isoformat(),
            "eventCount": len(session.events)
        }
        for session in sessions.values()
        if session.userId == user_id and session.appName == app_name
    ]
    return {"sessions": user_sessions}

@app.get("/apps/{app_name}/users/{user_id}/sessions/{session_id}")
async def get_session(app_name: str, user_id: str, session_id: str):
    """Get a specific session"""
    # Handle undefined/null session_id
    if session_id in ["undefined", "null", ""]:
        # Create a new session if undefined
        new_session_id = str(uuid.uuid4())
        session = Session(
            id=new_session_id,
            appName=app_name,
            userId=user_id,
            createdAt=datetime.now()
        )
        sessions[new_session_id] = session
        logger.info(f"Created new session {new_session_id} for undefined session request")
        return {
            "id": session.id,
            "appName": session.appName,
            "userId": session.userId,
            "createdAt": session.createdAt.isoformat(),
            "events": session.events,
            "state": session.state
        }
    
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    if session.userId != user_id or session.appName != app_name:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return {
        "id": session.id,
        "appName": session.appName,
        "userId": session.userId,
        "createdAt": session.createdAt.isoformat(),
        "events": session.events,
        "state": session.state
    }

@app.delete("/apps/{app_name}/users/{user_id}/sessions/{session_id}")
async def delete_session(app_name: str, user_id: str, session_id: str):
    """Delete a session"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    if session.userId != user_id or session.appName != app_name:
        raise HTTPException(status_code=403, detail="Access denied")
    
    del sessions[session_id]
    logger.info(f"Deleted session {session_id}")
    return {"status": "deleted"}

@app.post("/apps/{app_name}/users/{user_id}/sessions")
async def import_session(app_name: str, user_id: str, session_data: dict):
    """Import a session with events"""
    session_id = str(uuid.uuid4())
    session = Session(
        id=session_id,
        appName=app_name,
        userId=user_id,
        createdAt=datetime.now(),
        events=session_data.get("events", [])
    )
    sessions[session_id] = session
    return {"sessionId": session_id, "status": "imported"}

# Evaluation endpoints
@app.get("/apps/{app_name}/eval_sets")
async def get_eval_sets(app_name: str):
    """Get all evaluation sets for an app"""
    app_eval_sets = [
        {"id": eval_set.id, "name": eval_set.name, "caseCount": len(eval_set.cases)}
        for eval_set in eval_sets.values()
    ]
    return {"evalSets": app_eval_sets}

@app.post("/apps/{app_name}/eval_sets/{eval_set_id}")
async def create_eval_set(app_name: str, eval_set_id: str):
    """Create a new evaluation set"""
    eval_set = EvalSet(id=eval_set_id, name=eval_set_id)
    eval_sets[eval_set_id] = eval_set
    return {"status": "created", "evalSetId": eval_set_id}

@app.get("/apps/{app_name}/eval_sets/{eval_set_id}/evals")
async def list_eval_cases(app_name: str, eval_set_id: str):
    """List evaluation cases in a set"""
    if eval_set_id not in eval_sets:
        raise HTTPException(status_code=404, detail="Eval set not found")
    
    eval_set = eval_sets[eval_set_id]
    return {"cases": [case.dict() for case in eval_set.cases]}

@app.post("/apps/{app_name}/eval_sets/{eval_set_id}/add_session")
async def add_session_to_eval(app_name: str, eval_set_id: str, request: dict):
    """Add a session to an evaluation set"""
    # Implementation for adding session to eval set
    return {"status": "added"}

@app.post("/apps/{app_name}/eval_sets/{eval_set_id}/run_eval")
async def run_evaluation(app_name: str, eval_set_id: str, request: dict):
    """Run evaluation on specified cases"""
    eval_ids = request.get("evalIds", [])
    eval_metrics = request.get("evalMetrics", [])
    
    # Simulate evaluation run
    result_id = str(uuid.uuid4())
    return {"status": "started", "evalResultId": result_id}

@app.get("/apps/{app_name}/eval_results")
async def list_eval_results(app_name: str):
    """List evaluation results"""
    # Return mock results
    return {"results": []}

@app.get("/apps/{app_name}/eval_results/{result_id}")
async def get_eval_result(app_name: str, result_id: str):
    """Get specific evaluation result"""
    return {"id": result_id, "status": "completed", "metrics": {}}

# Debug/Tracing endpoints
@app.get("/debug/trace/{trace_id}")
async def get_event_trace(trace_id: str):
    """Get event trace by ID"""
    return {"traceId": trace_id, "events": [], "timeline": []}

@app.get("/debug/trace/session/{session_id}")
async def get_session_trace(session_id: str):
    """Get trace for a session"""
    # Handle undefined/null session_id
    if session_id in ["undefined", "null", ""]:
        return {"sessionId": session_id, "trace": [], "performance": {}, "message": "No trace available for undefined session"}
    
    if session_id in sessions:
        session = sessions[session_id]
        # Convert events to trace format
        trace_events = []
        for event in session.events:
            trace_events.append({
                "id": event["id"],
                "timestamp": event["timestamp"],
                "type": event["type"],
                "role": event["role"],
                "content": event.get("content", {}),
                "sessionId": event["sessionId"]
            })
        
        return {
            "sessionId": session_id, 
            "trace": trace_events, 
            "performance": {
                "totalEvents": len(trace_events),
                "userMessages": len([e for e in trace_events if e["role"] == "user"]),
                "agentMessages": len([e for e in trace_events if e["role"] == "assistant"])
            }
        }
    
    return {"sessionId": session_id, "trace": [], "performance": {}}

@app.get("/apps/{app_name}/users/{user_id}/sessions/{session_id}/events/{event_id}/graph")
async def get_event_graph(app_name: str, user_id: str, session_id: str, event_id: str):
    """Get event graph visualization"""
    return {"dotSrc": "digraph G { A -> B; B -> C; }"}

# Artifact endpoints
@app.get("/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name}")
async def get_latest_artifact(app_name: str, user_id: str, session_id: str, artifact_name: str):
    """Get latest version of an artifact"""
    artifact_key = f"{session_id}:{artifact_name}"
    if artifact_key in artifacts:
        return artifacts[artifact_key].dict()
    
    # Return mock artifact
    return {
        "id": str(uuid.uuid4()),
        "name": artifact_name,
        "content": {"type": "text", "data": f"Sample content for {artifact_name}"},
        "version": "1.0",
        "createdAt": datetime.now().isoformat()
    }

@app.get("/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name}/versions/{version_id}")
async def get_artifact_version(app_name: str, user_id: str, session_id: str, artifact_name: str, version_id: str):
    """Get specific version of an artifact"""
    return {
        "id": version_id,
        "name": artifact_name,
        "content": {"type": "text", "data": f"Version {version_id} of {artifact_name}"},
        "version": version_id,
        "createdAt": datetime.now().isoformat()
    }

# WebSocket endpoint for real-time communication
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_connections.append(websocket)
    logger.info("WebSocket connection established")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            logger.info(f"Received WebSocket message: {message}")
            
            # Echo back or process message
            response = {
                "type": "response",
                "content": f"Received: {message}",
                "timestamp": datetime.now().isoformat()
            }
            
            await websocket.send_text(json.dumps(response))
            
    except WebSocketDisconnect:
        websocket_connections.remove(websocket)
        logger.info("WebSocket connection closed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
