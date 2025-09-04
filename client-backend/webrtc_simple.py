"""
Simplified WebRTC manager using browser-native WebRTC through frontend
This replaces the aiortc-based implementation to avoid compilation issues
"""
import json
import asyncio
import logging
import uuid
from typing import Dict, Optional, Callable
import websockets
import ssl

logger = logging.getLogger(__name__)

class SimpleWebRTCManager:
    def __init__(self, client_id: str, server_url: str):
        self.client_id = client_id
        self.server_url = server_url
        self.server_ws: Optional[websockets.WebSocketServerProtocol] = None
        self.peer_connections: Dict[str, dict] = {}
        self.message_handlers: Dict[str, Callable] = {}
        self.is_connected = False
        
    async def connect_to_server(self):
        """Connect to signaling server"""
        try:
            uri = f"{self.server_url}/ws/{self.client_id}"
            logger.info(f"Connecting to signaling server: {uri}")
            
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            self.server_ws = await websockets.connect(uri, ssl=ssl_context)
            self.is_connected = True
            
            # Register with server
            registration_msg = {
                "type": "register",
                "device_name": f"WebRTC-Client-{self.client_id[:8]}",
                "ip_address": "127.0.0.1",
                "local_port": 8001
            }
            logger.info(f"Sending registration: {registration_msg}")
            await self._send_to_server(registration_msg)
            
            # Start listening for signaling messages
            asyncio.create_task(self._listen_for_signaling())
            
            logger.info("Connected to signaling server")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to signaling server: {e}")
            self.is_connected = False
            return False
    
    async def _send_to_server(self, message: dict):
        """Send message to signaling server"""
        if self.server_ws and self.is_connected:
            try:
                await self.server_ws.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to send message to server: {e}")
                self.is_connected = False
    
    async def _listen_for_signaling(self):
        """Listen for signaling messages from server"""
        try:
            while self.is_connected and self.server_ws:
                message = await self.server_ws.recv()
                data = json.loads(message)
                await self._handle_signaling_message(data)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("Signaling server connection closed")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Error in signaling listener: {e}")
            self.is_connected = False
    
    async def _handle_signaling_message(self, message: dict):
        """Handle signaling messages from server"""
        msg_type = message.get("type")
        
        if msg_type == "registration_success":
            logger.info(f"Successfully registered with server as {message.get('client_id')}")
            
        elif msg_type == "offer":
            # Forward WebRTC offer to frontend
            await self._notify_frontend("webrtc_offer", {
                "from_peer": message.get("from_client"),
                "offer": message.get("data", {})
            })
            
        elif msg_type == "answer":
            # Forward WebRTC answer to frontend
            await self._notify_frontend("webrtc_answer", {
                "from_peer": message.get("from_client"),
                "answer": message.get("data", {})
            })
            
        elif msg_type == "ice_candidate":
            # Forward ICE candidate to frontend
            await self._notify_frontend("webrtc_ice_candidate", {
                "from_peer": message.get("from_client"),
                "candidate": message.get("data", {})
            })
            
        elif msg_type == "pong":
            # Handle ping response
            pass
            
        else:
            logger.warning(f"Unknown signaling message type: {msg_type}")
    
    async def _notify_frontend(self, event_type: str, data: dict):
        """Notify frontend about WebRTC events"""
        # This will be handled by the frontend WebSocket connection
        handler = self.message_handlers.get(event_type)
        if handler:
            await handler(data)
    
    def register_message_handler(self, message_type: str, handler: Callable):
        """Register handler for specific message types"""
        self.message_handlers[message_type] = handler
    
    async def send_offer_to_peer(self, peer_id: str, offer: dict):
        """Send WebRTC offer to peer through signaling server"""
        await self._send_to_server({
            "type": "offer",
            "to_client": peer_id,
            "data": offer
        })
    
    async def send_answer_to_peer(self, peer_id: str, answer: dict):
        """Send WebRTC answer to peer through signaling server"""
        await self._send_to_server({
            "type": "answer",
            "to_client": peer_id,
            "data": answer
        })
    
    async def send_ice_candidate_to_peer(self, peer_id: str, candidate: dict):
        """Send ICE candidate to peer through signaling server"""
        await self._send_to_server({
            "type": "ice_candidate",
            "to_client": peer_id,
            "data": candidate
        })
    
    async def initiate_connection(self, peer_id: str) -> bool:
        """Initiate WebRTC connection with peer (handled by frontend)"""
        try:
            # Notify frontend to initiate WebRTC connection
            await self._notify_frontend("initiate_webrtc_connection", {
                "peer_id": peer_id
            })
            return True
        except Exception as e:
            logger.error(f"Failed to initiate connection with {peer_id}: {e}")
            return False
    
    async def send_data_to_peer(self, peer_id: str, data: dict, channel_label: str = "file_transfer") -> bool:
        """Send data to peer (handled by frontend WebRTC data channel)"""
        try:
            # Notify frontend to send data through WebRTC data channel
            await self._notify_frontend("send_webrtc_data", {
                "peer_id": peer_id,
                "data": data,
                "channel": channel_label
            })
            return True
        except Exception as e:
            logger.error(f"Failed to send data to {peer_id}: {e}")
            return False
    
    async def close_all_connections(self):
        """Close all connections"""
        self.is_connected = False
        if self.server_ws:
            await self.server_ws.close()
        self.peer_connections.clear()
        logger.info("All WebRTC connections closed")
