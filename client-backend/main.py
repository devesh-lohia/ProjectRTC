from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import os
import json
import asyncio
import websockets
import uuid
import hashlib
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging
import psutil
import aiofiles
from datetime import datetime

from webrtc_manager import WebRTCManager
from file_transfer import FileTransferManager, TransferStatus
from config import *
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application lifespan events"""
    # Startup
    logger.info(f"Starting DriveRTC Client - {DEVICE_NAME}")
    logger.info(f"Shared folder: {SHARED_FOLDER}")
    
    # Initialize managers
    await initialize_managers()
    
    yield
    
    # Shutdown
    if webrtc_manager:
        await webrtc_manager.close_all_connections()
    logger.info("DriveRTC Client shutdown complete")

app = FastAPI(title="DriveRTC Client", version="1.0.0", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
webrtc_manager: Optional[WebRTCManager] = None
file_transfer_manager: Optional[FileTransferManager] = None
frontend_connections: List[WebSocket] = []

# Data models
class FileInfo(BaseModel):
    name: str
    path: str
    size: int
    is_directory: bool
    modified_time: str
    file_hash: Optional[str] = None

class TransferRequest(BaseModel):
    file_paths: List[str]
    target_client: str
    operation: str  # 'copy', 'move', 'download'

class ChunkInfo(BaseModel):
    file_id: str
    chunk_index: int
    total_chunks: int
    data: bytes
    chunk_hash: str

# Ensure shared folder exists
os.makedirs(SHARED_FOLDER, exist_ok=True)

def get_file_hash(file_path: str) -> str:
    """Generate SHA256 hash of file"""
    hash_sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    except Exception:
        return ""

def scan_directory(directory_path: str) -> List[FileInfo]:
    """Recursively scan directory and return file information"""
    files = []
    try:
        for root, dirs, filenames in os.walk(directory_path):
            # Add directories
            for dirname in dirs:
                dir_path = os.path.join(root, dirname)
                rel_path = os.path.relpath(dir_path, directory_path)
                try:
                    stat = os.stat(dir_path)
                    files.append(FileInfo(
                        name=dirname,
                        path=rel_path,
                        size=0,
                        is_directory=True,
                        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat()
                    ))
                except Exception as e:
                    logger.error(f"Error accessing directory {dir_path}: {e}")
            
            # Add files
            for filename in filenames:
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, directory_path)
                try:
                    stat = os.stat(file_path)
                    files.append(FileInfo(
                        name=filename,
                        path=rel_path,
                        size=stat.st_size,
                        is_directory=False,
                        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        file_hash=get_file_hash(file_path) if stat.st_size < 100 * 1024 * 1024 else None  # Hash files < 100MB
                    ))
                except Exception as e:
                    logger.error(f"Error accessing file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error scanning directory {directory_path}: {e}")
    
    return files

async def initialize_managers():
    """Initialize WebRTC and file transfer managers"""
    global webrtc_manager, file_transfer_manager
    
    webrtc_manager = WebRTCManager(CLIENT_ID, SERVER_URL)
    file_transfer_manager = FileTransferManager(SHARED_FOLDER, CHUNK_SIZE)
    
    # Register message handlers
    webrtc_manager.register_message_handler("transfer_init", file_transfer_manager.handle_transfer_init)
    webrtc_manager.register_message_handler("file_metadata", file_transfer_manager.handle_file_metadata)
    webrtc_manager.register_message_handler("chunk_metadata", file_transfer_manager.handle_chunk_metadata)
    webrtc_manager.register_message_handler("file_chunk", file_transfer_manager.handle_file_chunk)
    webrtc_manager.register_message_handler("transfer_complete", file_transfer_manager.handle_transfer_complete)
    
    # Connect to server
    await webrtc_manager.connect_to_server()

async def broadcast_to_frontend(message: dict):
    """Broadcast message to all connected frontend clients"""
    if frontend_connections:
        message_str = json.dumps(message)
        for websocket in frontend_connections.copy():
            try:
                await websocket.send_text(message_str)
            except Exception:
                frontend_connections.remove(websocket)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application lifespan events"""
    # Startup
    logger.info(f"Starting DriveRTC Client - {DEVICE_NAME}")
    logger.info(f"Shared folder: {SHARED_FOLDER}")
    
    # Initialize managers
    await initialize_managers()
    
    yield
    
    # Shutdown
    if webrtc_manager:
        await webrtc_manager.close_all_connections()
    logger.info("DriveRTC Client shutdown complete")

@app.get("/")
async def root():
    return {
        "message": "DriveRTC Client Backend",
        "client_id": CLIENT_ID,
        "device_name": DEVICE_NAME,
        "shared_folder": SHARED_FOLDER
    }

@app.get("/files")
async def list_files(path: str = ""):
    """List files and directories in shared folder"""
    try:
        full_path = os.path.join(SHARED_FOLDER, path) if path else SHARED_FOLDER
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="Path not found")
        
        if not os.path.isdir(full_path):
            raise HTTPException(status_code=400, detail="Path is not a directory")
        
        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            rel_path = os.path.join(path, item) if path else item
            
            try:
                stat = os.stat(item_path)
                files.append(FileInfo(
                    name=item,
                    path=rel_path,
                    size=stat.st_size if os.path.isfile(item_path) else 0,
                    is_directory=os.path.isdir(item_path),
                    modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    file_hash=get_file_hash(item_path) if os.path.isfile(item_path) and stat.st_size < 10*1024*1024 else None
                ))
            except Exception as e:
                logger.error(f"Error accessing {item_path}: {e}")
        
        return {"files": files, "current_path": path}
    
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download a file from shared folder"""
    try:
        full_path = os.path.join(SHARED_FOLDER, file_path)
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        if os.path.isdir(full_path):
            # Create zip for directory
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(full_path):
                    for file in files:
                        file_path_in_zip = os.path.join(root, file)
                        arcname = os.path.relpath(file_path_in_zip, full_path)
                        zipf.write(file_path_in_zip, arcname)
            
            return FileResponse(
                temp_zip.name,
                media_type='application/zip',
                filename=f"{os.path.basename(full_path)}.zip"
            )
        else:
            return FileResponse(full_path, filename=os.path.basename(full_path))
    
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), path: str = ""):
    """Upload file to shared folder"""
    try:
        target_dir = os.path.join(SHARED_FOLDER, path) if path else SHARED_FOLDER
        os.makedirs(target_dir, exist_ok=True)
        
        file_path = os.path.join(target_dir, file.filename)
        
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        return {"message": "File uploaded successfully", "path": file_path}
    
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete/{file_path:path}")
async def delete_file(file_path: str):
    """Delete file or directory"""
    try:
        full_path = os.path.join(SHARED_FOLDER, file_path)
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        
        return {"message": "File deleted successfully"}
    
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for frontend communication"""
    await websocket.accept()
    frontend_connections.append(websocket)
    
    try:
        # Send initial client info
        await websocket.send_text(json.dumps({
            "type": "client_info",
            "client_id": CLIENT_ID,
            "device_name": DEVICE_NAME,
            "shared_folder": SHARED_FOLDER
        }))
        
        # Request peer list from server (removed - not needed for frontend websocket)
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "get_files":
                path = message.get("path", "")
                files_data = await list_files(path)
                await websocket.send_text(json.dumps({
                    "type": "files_list",
                    "data": files_data
                }))
            
            elif message["type"] == "transfer_request":
                # Handle file transfer request
                await handle_transfer_request(message, websocket)
                
    except WebSocketDisconnect:
        frontend_connections.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in frontend_connections:
            frontend_connections.remove(websocket)

async def handle_transfer_request(message: dict, websocket: WebSocket):
    """Handle file transfer requests between clients"""
    try:
        file_paths = message.get("file_paths", [])
        target_peer = message.get("target_peer")
        operation = message.get("operation", "copy")
        
        if not file_paths or not target_peer:
            await websocket.send_text(json.dumps({
                "type": "transfer_error",
                "error": "Missing file paths or target peer"
            }))
            return
        
        # Check if connected to target peer
        if not webrtc_manager.is_connected_to_peer(target_peer):
            # Initiate connection
            success = await webrtc_manager.initiate_connection(target_peer)
            if not success:
                await websocket.send_text(json.dumps({
                    "type": "transfer_error",
                    "error": "Failed to connect to target peer"
                }))
                return
        
        # Start file transfer
        async def progress_callback(transfer_info):
            await websocket.send_text(json.dumps({
                "type": "transfer_progress",
                "transfer_id": transfer_info.transfer_id,
                "progress": transfer_info.progress,
                "status": transfer_info.status.value,
                "transferred_size": transfer_info.transferred_size,
                "total_size": transfer_info.total_size
            }))
        
        transfer_id = await file_transfer_manager.start_file_transfer(
            file_paths, target_peer, operation, webrtc_manager, progress_callback
        )
        
        await websocket.send_text(json.dumps({
            "type": "transfer_started",
            "transfer_id": transfer_id,
            "status": "initiated"
        }))
        
    except Exception as e:
        logger.error(f"Error handling transfer request: {e}")
        await websocket.send_text(json.dumps({
            "type": "transfer_error",
            "error": str(e)
        }))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
