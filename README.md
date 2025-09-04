# DriveRTC - P2P File Sharing System

A peer-to-peer file sharing system using WebRTC for direct client-to-client communication, similar to Google Drive but with decentralized file transfers.

## Architecture

### Server Backend (Python FastAPI + Firebase)
- Acts as ICE/STUN server for WebRTC connection establishment
- Handles client registration and discovery
- No file storage - purely for signaling

### Client Backend (Python FastAPI)
- Runs locally on each user's machine
- Provides file system access to designated folders
- Handles WebRTC peer connections
- Manages file chunking and transfer

### Frontend (React)
- Web-based interface accessible via browser
- Shows connected devices as folders
- File/folder operations: open, download, copy, paste, delete
- Real-time file transfer progress

## Features

- **P2P File Transfer**: Direct WebRTC connections between clients
- **File Chunking**: Torrent-like chunked file transfer for reliability
- **Multi-file Operations**: Zip/unzip for batch operations
- **Cross-platform**: Works on macOS and Linux
- **Real-time Sync**: Live folder structure updates

## Setup

1. **Server Backend**: Deploy to Firebase
2. **Client Backend**: Install on each device
3. **Frontend**: Access via web browser

## File Operations

- **Open**: Navigate into folders
- **Download**: Transfer files from remote client
- **Copy/Paste**: P2P transfer between clients
- **Delete**: Remove files from remote client
- **Multi-select**: Batch operations with automatic zipping
