from typing import List, Optional, Any, Dict
from datetime import datetime

# Simple data classes without Pydantic for compatibility
class AgentRunRequest:
    def __init__(self, appName: str, userId: str, sessionId: str, newMessage: Any, 
                 functionCallEventId: Optional[str] = None, streaming: Optional[bool] = True, 
                 stateDelta: Optional[Any] = None):
        self.appName = appName
        self.userId = userId
        self.sessionId = sessionId
        self.newMessage = newMessage
        self.functionCallEventId = functionCallEventId
        self.streaming = streaming
        self.stateDelta = stateDelta

class Session:
    def __init__(self, id: str, appName: str, userId: str, createdAt: datetime, events: List[Dict] = None, state: Dict = None):
        self.id = id
        self.appName = appName
        self.userId = userId
        self.createdAt = createdAt
        self.events = events or []
        self.state = state or {}

class EvalCase:
    def __init__(self, id: str, conversation: List[Dict], sessionInput: Dict, creationTimestamp: datetime):
        self.id = id
        self.conversation = conversation
        self.sessionInput = sessionInput
        self.creationTimestamp = creationTimestamp
    
    def dict(self):
        return {
            "id": self.id,
            "conversation": self.conversation,
            "sessionInput": self.sessionInput,
            "creationTimestamp": self.creationTimestamp.isoformat()
        }

class EvalSet:
    def __init__(self, id: str, name: str, cases: List[EvalCase] = None):
        self.id = id
        self.name = name
        self.cases = cases or []

class LiveRequest:
    def __init__(self, content: Optional[Any] = None, blob: Optional[Any] = None, 
                 close: Optional[bool] = False, model_configuration: Optional[Any] = None):
        self.content = content
        self.blob = blob
        self.close = close
        self.model_configuration = model_configuration

class Artifact:
    def __init__(self, id: str, name: str, content: Any, version: str, createdAt: datetime):
        self.id = id
        self.name = name
        self.content = content
        self.version = version
        self.createdAt = createdAt
    
    def dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "version": self.version,
            "createdAt": self.createdAt.isoformat()
        }
