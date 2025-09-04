import os
import uuid
import psutil
from pathlib import Path

# Server configuration
SERVER_URL = os.getenv("DRIVERTC_SERVER_URL", "ws://localhost:8000")
SERVER_HTTP_URL = os.getenv("DRIVERTC_SERVER_HTTP_URL", "http://localhost:8000")

# For production deployment, update these to your actual server URLs:
# SERVER_URL = "wss://your-server-domain.com"
# SERVER_HTTP_URL = "https://your-server-domain.com"

# Client configuration
CLIENT_ID = str(uuid.uuid4())
DEVICE_NAME = f"{psutil.users()[0].name if psutil.users() else 'Unknown'}-{os.uname().nodename}"

# File system configuration
SHARED_FOLDER = os.path.expanduser(os.getenv("DRIVERTC_SHARED_FOLDER", "~/DriveRTC_Shared"))
TEMP_FOLDER = os.path.join(SHARED_FOLDER, ".temp")
CHUNK_SIZE = int(os.getenv("DRIVERTC_CHUNK_SIZE", str(1024 * 1024)))  # 1MB default

# Transfer configuration
MAX_CONCURRENT_TRANSFERS = int(os.getenv("DRIVERTC_MAX_TRANSFERS", "5"))
TRANSFER_TIMEOUT = int(os.getenv("DRIVERTC_TRANSFER_TIMEOUT", "300"))  # 5 minutes

# WebRTC configuration
ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]

# Ensure directories exist
os.makedirs(SHARED_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
