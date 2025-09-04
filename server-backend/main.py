from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import uuid
from typing import Dict, List, Optional
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DriveRTC Server", version="1.0.0")

# CORS middleware for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class ClientInfo(BaseModel):
    client_id: str
    device_name: str
    ip_address: Optional[str] = None
    local_port: Optional[int] = None
    status: str = "online"
    last_seen: float = 0

class SignalingMessage(BaseModel):
    type: str
    from_client: str
    to_client: str
    data: dict

# In-memory storage for connected clients
connected_clients: Dict[str, WebSocket] = {}
client_info: Dict[str, ClientInfo] = {}

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"Client {client_id} connected")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in client_info:
            del client_info[client_id]
        logger.info(f"Client {client_id} disconnected")

    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)

    async def broadcast_client_list(self):
        """Broadcast updated client list to all connected clients"""
        clients_list = [
            {
                "client_id": cid,
                "device_name": info.device_name,
                "status": info.status
            }
            for cid, info in client_info.items()
        ]
        
        message = {
            "type": "client_list_update",
            "clients": clients_list
        }
        
        for client_id in self.active_connections:
            await self.send_personal_message(json.dumps(message), client_id)

manager = ConnectionManager()

@app.get("/")
async def root():
    return {"message": "DriveRTC Server - ICE/STUN Signaling Server"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "connected_clients": len(connected_clients),
        "active_connections": len(manager.active_connections)
    }

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "register":
                # Register client with device info
                client_info[client_id] = ClientInfo(
                    client_id=client_id,
                    device_name=message.get("device_name", f"Device-{client_id[:8]}"),
                    ip_address=message.get("ip_address"),
                    local_port=message.get("local_port", 8001),
                    status="online",
                    last_seen=asyncio.get_event_loop().time()
                )
                
                # Send registration confirmation
                await manager.send_personal_message(
                    json.dumps({
                        "type": "registration_success",
                        "client_id": client_id
                    }),
                    client_id
                )
                
                # Broadcast updated client list
                await manager.broadcast_client_list()
                
            elif message["type"] == "get_clients":
                # Send current client list
                clients_list = [
                    {
                        "client_id": cid,
                        "device_name": info.device_name,
                        "status": info.status,
                        "ip_address": info.ip_address,
                        "local_port": info.local_port,
                        "last_seen": info.last_seen
                    }
                    for cid, info in client_info.items()
                    if cid != client_id  # Don't include self
                ]
                
                await manager.send_personal_message(
                    json.dumps({
                        "type": "client_list",
                        "clients": clients_list
                    }),
                    client_id
                )
                
            elif message["type"] in ["offer", "answer", "ice_candidate"]:
                # WebRTC signaling - forward to target client
                target_client = message.get("to_client")
                if target_client and target_client in manager.active_connections:
                    signaling_message = {
                        "type": message["type"],
                        "from_client": client_id,
                        "data": message.get("data", {})
                    }
                    
                    await manager.send_personal_message(
                        json.dumps(signaling_message),
                        target_client
                    )
                    
            elif message["type"] == "ping":
                # Keep-alive ping and update last_seen
                if client_id in client_info:
                    client_info[client_id].last_seen = asyncio.get_event_loop().time()
                await manager.send_personal_message(
                    json.dumps({"type": "pong"}),
                    client_id
                )
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        await manager.broadcast_client_list()
    except Exception as e:
        logger.error(f"Error in websocket connection for {client_id}: {e}")
        manager.disconnect(client_id)
        await manager.broadcast_client_list()

# ICE/STUN server configuration endpoint
@app.get("/ice-servers")
async def get_ice_servers():
    """Return ICE server configuration for WebRTC"""
    return {
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "stun:stun1.l.google.com:19302"},
            {"urls": "stun:stun2.l.google.com:19302"},
            # Add TURN servers here if needed
        ]
    }

@app.get("/clients")
async def get_connected_clients():
    """Get list of connected clients with their addresses"""
    current_time = asyncio.get_event_loop().time()
    
    # Filter out stale clients (offline for more than 60 seconds)
    active_clients = []
    for cid, info in client_info.items():
        if current_time - info.last_seen < 60:  # 60 seconds timeout
            active_clients.append({
                "client_id": cid,
                "device_name": info.device_name,
                "status": info.status,
                "ip_address": info.ip_address,
                "local_port": info.local_port,
                "backend_url": f"http://{info.ip_address}:{info.local_port}" if info.ip_address else None,
                "websocket_url": f"ws://{info.ip_address}:{info.local_port}" if info.ip_address else None,
                "last_seen": info.last_seen,
                "online": cid in manager.active_connections
            })
    
    return {
        "clients": active_clients,
        "total_count": len(active_clients),
        "server_time": current_time
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
