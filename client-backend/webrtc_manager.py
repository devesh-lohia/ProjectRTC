import asyncio
import json
import logging
import uuid
from typing import Dict, List, Optional, Callable
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCDataChannel
from aiortc.contrib.signaling import object_from_string, object_to_string
import websockets

logger = logging.getLogger(__name__)

class WebRTCManager:
    def __init__(self, client_id: str, server_url: str):
        self.client_id = client_id
        self.server_url = server_url
        self.peer_connections: Dict[str, RTCPeerConnection] = {}
        self.data_channels: Dict[str, RTCDataChannel] = {}
        self.server_ws: Optional[websockets.WebSocketServerProtocol] = None
        self.message_handlers: Dict[str, Callable] = {}
        self.ice_servers = [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "stun:stun1.l.google.com:19302"},
        ]
    
    async def connect_to_server(self):
        """Connect to signaling server"""
        try:
            self.server_ws = await websockets.connect(f"{self.server_url}/ws/{self.client_id}")
            logger.info(f"Connected to signaling server")
            
            # Get actual IP address
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except:
                local_ip = "localhost"
            
            # Register with server
            await self.server_ws.send(json.dumps({
                "type": "register",
                "device_name": f"Client-{self.client_id[:8]}",
                "ip_address": local_ip,
                "local_port": 8001
            }))
            
            # Start listening for messages
            asyncio.create_task(self._handle_server_messages())
            return True
        except Exception as e:
            logger.error(f"Failed to connect to server: {e}")
            return False
    
    async def _handle_server_messages(self):
        """Handle incoming signaling messages"""
        try:
            async for message in self.server_ws:
                data = json.loads(message)
                await self._process_signaling_message(data)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Server connection closed")
        except Exception as e:
            logger.error(f"Error handling server messages: {e}")
    
    async def _process_signaling_message(self, data: dict):
        """Process signaling messages from server"""
        message_type = data.get("type")
        
        if message_type == "offer":
            await self._handle_offer(data)
        elif message_type == "answer":
            await self._handle_answer(data)
        elif message_type == "ice_candidate":
            await self._handle_ice_candidate(data)
    
    async def create_peer_connection(self, peer_id: str) -> RTCPeerConnection:
        """Create a new peer connection"""
        pc = RTCPeerConnection(configuration={"iceServers": self.ice_servers})
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"Connection state for {peer_id}: {pc.connectionState}")
            if pc.connectionState == "connected":
                logger.info(f"Successfully connected to peer {peer_id}")
            elif pc.connectionState == "failed":
                logger.error(f"Connection failed to peer {peer_id}")
        
        @pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"Data channel received from {peer_id}: {channel.label}")
            self.data_channels[f"{peer_id}_{channel.label}"] = channel
            self._setup_data_channel_handlers(channel, peer_id)
        
        self.peer_connections[peer_id] = pc
        return pc
    
    def _setup_data_channel_handlers(self, channel: RTCDataChannel, peer_id: str):
        """Setup handlers for data channel"""
        @channel.on("open")
        def on_open():
            logger.info(f"Data channel {channel.label} opened with {peer_id}")
        
        @channel.on("message")
        def on_message(message):
            try:
                if isinstance(message, str):
                    data = json.loads(message)
                    self._handle_data_channel_message(data, peer_id, channel.label)
                else:
                    # Binary data (file chunks)
                    self._handle_binary_data(message, peer_id, channel.label)
            except Exception as e:
                logger.error(f"Error handling data channel message: {e}")
    
    def _handle_data_channel_message(self, data: dict, peer_id: str, channel_label: str):
        """Handle JSON messages from data channel"""
        message_type = data.get("type")
        handler = self.message_handlers.get(message_type)
        
        if handler:
            asyncio.create_task(handler(data, peer_id, channel_label))
        else:
            logger.warning(f"No handler for message type: {message_type}")
    
    def _handle_binary_data(self, data: bytes, peer_id: str, channel_label: str):
        """Handle binary data from data channel"""
        # This would be file chunk data
        handler = self.message_handlers.get("file_chunk")
        if handler:
            asyncio.create_task(handler(data, peer_id, channel_label))
    
    async def initiate_connection(self, peer_id: str) -> bool:
        """Initiate connection to a peer"""
        try:
            pc = await self.create_peer_connection(peer_id)
            
            # Create data channel for file transfer
            channel = pc.createDataChannel("file_transfer", ordered=True)
            self.data_channels[f"{peer_id}_file_transfer"] = channel
            self._setup_data_channel_handlers(channel, peer_id)
            
            # Create offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            
            # Send offer via signaling server
            await self._send_signaling_message({
                "type": "offer",
                "to_client": peer_id,
                "data": {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type
                }
            })
            
            return True
        except Exception as e:
            logger.error(f"Failed to initiate connection to {peer_id}: {e}")
            return False
    
    async def _handle_offer(self, data: dict):
        """Handle incoming offer"""
        peer_id = data["from_client"]
        offer_data = data["data"]
        
        try:
            pc = await self.create_peer_connection(peer_id)
            
            # Set remote description
            offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
            await pc.setRemoteDescription(offer)
            
            # Create answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            
            # Send answer via signaling server
            await self._send_signaling_message({
                "type": "answer",
                "to_client": peer_id,
                "data": {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type
                }
            })
            
        except Exception as e:
            logger.error(f"Failed to handle offer from {peer_id}: {e}")
    
    async def _handle_answer(self, data: dict):
        """Handle incoming answer"""
        peer_id = data["from_client"]
        answer_data = data["data"]
        
        try:
            pc = self.peer_connections.get(peer_id)
            if pc:
                answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
                await pc.setRemoteDescription(answer)
        except Exception as e:
            logger.error(f"Failed to handle answer from {peer_id}: {e}")
    
    async def _handle_ice_candidate(self, data: dict):
        """Handle incoming ICE candidate"""
        peer_id = data["from_client"]
        candidate_data = data["data"]
        
        try:
            pc = self.peer_connections.get(peer_id)
            if pc and candidate_data:
                candidate = RTCIceCandidate(
                    component=candidate_data["component"],
                    foundation=candidate_data["foundation"],
                    ip=candidate_data["ip"],
                    port=candidate_data["port"],
                    priority=candidate_data["priority"],
                    protocol=candidate_data["protocol"],
                    type=candidate_data["type"]
                )
                await pc.addIceCandidate(candidate)
        except Exception as e:
            logger.error(f"Failed to handle ICE candidate from {peer_id}: {e}")
    
    async def _send_signaling_message(self, message: dict):
        """Send message via signaling server"""
        if self.server_ws:
            await self.server_ws.send(json.dumps(message))
    
    async def send_data_to_peer(self, peer_id: str, data: dict, channel_label: str = "file_transfer"):
        """Send JSON data to peer via data channel"""
        channel_key = f"{peer_id}_{channel_label}"
        channel = self.data_channels.get(channel_key)
        
        if channel and channel.readyState == "open":
            await channel.send(json.dumps(data))
            return True
        else:
            logger.error(f"Data channel not available for peer {peer_id}")
            return False
    
    async def send_binary_to_peer(self, peer_id: str, data: bytes, channel_label: str = "file_transfer"):
        """Send binary data to peer via data channel"""
        channel_key = f"{peer_id}_{channel_label}"
        channel = self.data_channels.get(channel_key)
        
        if channel and channel.readyState == "open":
            channel.send(data)
            return True
        else:
            logger.error(f"Data channel not available for peer {peer_id}")
            return False
    
    def register_message_handler(self, message_type: str, handler: Callable):
        """Register handler for specific message type"""
        self.message_handlers[message_type] = handler
    
    def is_connected_to_peer(self, peer_id: str) -> bool:
        """Check if connected to specific peer"""
        pc = self.peer_connections.get(peer_id)
        return pc and pc.connectionState == "connected"
    
    async def close_connection(self, peer_id: str):
        """Close connection to specific peer"""
        pc = self.peer_connections.get(peer_id)
        if pc:
            await pc.close()
            del self.peer_connections[peer_id]
        
        # Clean up data channels
        channels_to_remove = [k for k in self.data_channels.keys() if k.startswith(f"{peer_id}_")]
        for channel_key in channels_to_remove:
            del self.data_channels[channel_key]
    
    async def close_all_connections(self):
        """Close all peer connections"""
        for peer_id in list(self.peer_connections.keys()):
            await self.close_connection(peer_id)
        
        if self.server_ws:
            await self.server_ws.close()
