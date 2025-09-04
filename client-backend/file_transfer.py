import asyncio
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Callable
import logging
import aiofiles
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class TransferStatus(Enum):
    PENDING = "pending"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class FileChunk:
    file_id: str
    chunk_index: int
    total_chunks: int
    data: bytes
    chunk_hash: str

@dataclass
class TransferInfo:
    transfer_id: str
    file_paths: List[str]
    target_peer: str
    operation: str  # 'copy', 'move', 'download'
    status: TransferStatus
    total_size: int
    transferred_size: int
    progress: float
    created_at: float
    updated_at: float

class FileTransferManager:
    def __init__(self, shared_folder: str, chunk_size: int = 1024 * 1024):
        self.shared_folder = Path(shared_folder)
        self.chunk_size = chunk_size
        self.active_transfers: Dict[str, TransferInfo] = {}
        self.file_chunks: Dict[str, Dict[int, FileChunk]] = {}  # file_id -> chunk_index -> chunk
        self.transfer_callbacks: Dict[str, Callable] = {}
        self.temp_folder = self.shared_folder / ".temp"
        self.temp_folder.mkdir(exist_ok=True)
    
    def generate_file_id(self, file_path: str) -> str:
        """Generate unique file ID"""
        return hashlib.sha256(f"{file_path}_{os.path.getmtime(file_path)}".encode()).hexdigest()[:16]
    
    def calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    async def prepare_files_for_transfer(self, file_paths: List[str], operation: str) -> tuple[str, int]:
        """Prepare files for transfer, return transfer_id and total_size"""
        transfer_id = hashlib.sha256(f"{','.join(file_paths)}_{asyncio.get_event_loop().time()}".encode()).hexdigest()[:16]
        
        total_size = 0
        prepared_files = []
        
        if len(file_paths) > 1 or operation == "copy_multiple":
            # Create zip file for multiple files/folders
            zip_path = self.temp_folder / f"{transfer_id}.zip"
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in file_paths:
                    full_path = self.shared_folder / file_path
                    
                    if full_path.is_file():
                        zipf.write(full_path, file_path)
                        total_size += full_path.stat().st_size
                    elif full_path.is_dir():
                        for root, dirs, files in os.walk(full_path):
                            for file in files:
                                file_full_path = Path(root) / file
                                arcname = str(Path(file_path) / file_full_path.relative_to(full_path))
                                zipf.write(file_full_path, arcname)
                                total_size += file_full_path.stat().st_size
            
            prepared_files = [str(zip_path.relative_to(self.shared_folder))]
            total_size = zip_path.stat().st_size
        else:
            # Single file/folder
            for file_path in file_paths:
                full_path = self.shared_folder / file_path
                if full_path.exists():
                    if full_path.is_file():
                        total_size += full_path.stat().st_size
                    else:
                        # For directories, calculate total size
                        for root, dirs, files in os.walk(full_path):
                            for file in files:
                                total_size += (Path(root) / file).stat().st_size
                    prepared_files.append(file_path)
        
        return transfer_id, total_size, prepared_files
    
    async def start_file_transfer(self, file_paths: List[str], target_peer: str, operation: str, 
                                webrtc_manager, progress_callback: Optional[Callable] = None) -> str:
        """Start file transfer to target peer"""
        transfer_id, total_size, prepared_files = await self.prepare_files_for_transfer(file_paths, operation)
        
        # Create transfer info
        transfer_info = TransferInfo(
            transfer_id=transfer_id,
            file_paths=prepared_files,
            target_peer=target_peer,
            operation=operation,
            status=TransferStatus.PENDING,
            total_size=total_size,
            transferred_size=0,
            progress=0.0,
            created_at=asyncio.get_event_loop().time(),
            updated_at=asyncio.get_event_loop().time()
        )
        
        self.active_transfers[transfer_id] = transfer_info
        
        if progress_callback:
            self.transfer_callbacks[transfer_id] = progress_callback
        
        # Send transfer initiation message
        await webrtc_manager.send_data_to_peer(target_peer, {
            "type": "transfer_init",
            "transfer_id": transfer_id,
            "files": prepared_files,
            "total_size": total_size,
            "operation": operation
        })
        
        # Start sending file chunks
        asyncio.create_task(self._send_file_chunks(transfer_id, webrtc_manager))
        
        return transfer_id
    
    async def _send_file_chunks(self, transfer_id: str, webrtc_manager):
        """Send file chunks to peer"""
        transfer_info = self.active_transfers.get(transfer_id)
        if not transfer_info:
            return
        
        transfer_info.status = TransferStatus.TRANSFERRING
        transfer_info.updated_at = asyncio.get_event_loop().time()
        
        try:
            for file_path in transfer_info.file_paths:
                full_path = self.shared_folder / file_path
                
                if not full_path.exists():
                    logger.error(f"File not found: {full_path}")
                    continue
                
                file_id = self.generate_file_id(str(full_path))
                file_size = full_path.stat().st_size
                total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
                
                # Send file metadata
                await webrtc_manager.send_data_to_peer(transfer_info.target_peer, {
                    "type": "file_metadata",
                    "transfer_id": transfer_id,
                    "file_id": file_id,
                    "file_path": file_path,
                    "file_size": file_size,
                    "total_chunks": total_chunks,
                    "file_hash": self.calculate_file_hash(full_path)
                })
                
                # Send chunks
                async with aiofiles.open(full_path, 'rb') as f:
                    for chunk_index in range(total_chunks):
                        chunk_data = await f.read(self.chunk_size)
                        chunk_hash = hashlib.sha256(chunk_data).hexdigest()
                        
                        # Send chunk metadata first
                        await webrtc_manager.send_data_to_peer(transfer_info.target_peer, {
                            "type": "chunk_metadata",
                            "transfer_id": transfer_id,
                            "file_id": file_id,
                            "chunk_index": chunk_index,
                            "chunk_size": len(chunk_data),
                            "chunk_hash": chunk_hash
                        })
                        
                        # Send chunk data
                        await webrtc_manager.send_binary_to_peer(transfer_info.target_peer, chunk_data)
                        
                        # Update progress
                        transfer_info.transferred_size += len(chunk_data)
                        transfer_info.progress = (transfer_info.transferred_size / transfer_info.total_size) * 100
                        transfer_info.updated_at = asyncio.get_event_loop().time()
                        
                        # Call progress callback
                        callback = self.transfer_callbacks.get(transfer_id)
                        if callback:
                            await callback(transfer_info)
                        
                        # Small delay to prevent overwhelming
                        await asyncio.sleep(0.001)
            
            # Mark transfer as completed
            transfer_info.status = TransferStatus.COMPLETED
            transfer_info.updated_at = asyncio.get_event_loop().time()
            
            # Send completion message
            await webrtc_manager.send_data_to_peer(transfer_info.target_peer, {
                "type": "transfer_complete",
                "transfer_id": transfer_id
            })
            
            # Clean up temp files
            await self._cleanup_transfer(transfer_id)
            
        except Exception as e:
            logger.error(f"Error sending file chunks for {transfer_id}: {e}")
            transfer_info.status = TransferStatus.FAILED
            transfer_info.updated_at = asyncio.get_event_loop().time()
    
    async def handle_transfer_init(self, data: dict, peer_id: str):
        """Handle incoming transfer initiation"""
        transfer_id = data["transfer_id"]
        files = data["files"]
        total_size = data["total_size"]
        operation = data["operation"]
        
        # Create transfer info for receiving
        transfer_info = TransferInfo(
            transfer_id=transfer_id,
            file_paths=files,
            target_peer=peer_id,
            operation=operation,
            status=TransferStatus.PENDING,
            total_size=total_size,
            transferred_size=0,
            progress=0.0,
            created_at=asyncio.get_event_loop().time(),
            updated_at=asyncio.get_event_loop().time()
        )
        
        self.active_transfers[transfer_id] = transfer_info
        logger.info(f"Receiving transfer {transfer_id} from {peer_id}")
    
    async def handle_file_metadata(self, data: dict, peer_id: str):
        """Handle incoming file metadata"""
        transfer_id = data["transfer_id"]
        file_id = data["file_id"]
        file_path = data["file_path"]
        file_size = data["file_size"]
        total_chunks = data["total_chunks"]
        file_hash = data["file_hash"]
        
        # Initialize chunk storage for this file
        self.file_chunks[file_id] = {}
        
        logger.info(f"Receiving file {file_path} ({file_size} bytes, {total_chunks} chunks)")
    
    async def handle_chunk_metadata(self, data: dict, peer_id: str):
        """Handle incoming chunk metadata"""
        # Store chunk metadata for verification
        pass
    
    async def handle_file_chunk(self, chunk_data: bytes, peer_id: str, transfer_id: str = None):
        """Handle incoming file chunk"""
        # This would be called when binary data is received
        # Implementation would need to match chunks with their metadata
        pass
    
    async def handle_transfer_complete(self, data: dict, peer_id: str):
        """Handle transfer completion"""
        transfer_id = data["transfer_id"]
        transfer_info = self.active_transfers.get(transfer_id)
        
        if transfer_info:
            # Assemble received files
            await self._assemble_received_files(transfer_id)
            
            transfer_info.status = TransferStatus.COMPLETED
            transfer_info.updated_at = asyncio.get_event_loop().time()
            
            logger.info(f"Transfer {transfer_id} completed")
    
    async def _assemble_received_files(self, transfer_id: str):
        """Assemble received file chunks into complete files"""
        transfer_info = self.active_transfers.get(transfer_id)
        if not transfer_info:
            return
        
        for file_id, chunks in self.file_chunks.items():
            if not chunks:
                continue
            
            # Sort chunks by index
            sorted_chunks = sorted(chunks.items())
            
            # Create output file path
            # This would need proper path handling based on the transfer
            output_path = self.shared_folder / "received" / f"{file_id}"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Assemble file
            async with aiofiles.open(output_path, 'wb') as f:
                for chunk_index, chunk in sorted_chunks:
                    await f.write(chunk.data)
            
            logger.info(f"Assembled file: {output_path}")
    
    async def _cleanup_transfer(self, transfer_id: str):
        """Clean up transfer resources"""
        # Remove temp files
        temp_file = self.temp_folder / f"{transfer_id}.zip"
        if temp_file.exists():
            temp_file.unlink()
        
        # Clean up chunk storage
        transfer_info = self.active_transfers.get(transfer_id)
        if transfer_info:
            for file_path in transfer_info.file_paths:
                file_id = self.generate_file_id(str(self.shared_folder / file_path))
                if file_id in self.file_chunks:
                    del self.file_chunks[file_id]
        
        # Remove callback
        if transfer_id in self.transfer_callbacks:
            del self.transfer_callbacks[transfer_id]
    
    def get_transfer_status(self, transfer_id: str) -> Optional[TransferInfo]:
        """Get transfer status"""
        return self.active_transfers.get(transfer_id)
    
    def get_active_transfers(self) -> List[TransferInfo]:
        """Get all active transfers"""
        return list(self.active_transfers.values())
    
    async def cancel_transfer(self, transfer_id: str):
        """Cancel active transfer"""
        transfer_info = self.active_transfers.get(transfer_id)
        if transfer_info:
            transfer_info.status = TransferStatus.CANCELLED
            transfer_info.updated_at = asyncio.get_event_loop().time()
            await self._cleanup_transfer(transfer_id)
