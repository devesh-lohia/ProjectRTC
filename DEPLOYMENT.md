# DriveRTC Deployment Guide

## Quick Start

### Local Development

1. **Run setup script:**
   ```bash
   ./setup.sh
   ```

2. **Start services in separate terminals:**
   ```bash
   # Terminal 1 - Server Backend
   cd server-backend
   python main.py

   # Terminal 2 - Client Backend
   cd client-backend
   python main.py

   # Terminal 3 - Frontend
   cd frontend
   npm start
   ```

3. **Access the application:**
   - Web Interface: http://localhost:3000
   - Client Backend API: http://localhost:8001
   - Server Backend API: http://localhost:8000

### Docker Deployment

```bash
docker-compose up --build
```

## Production Deployment

### Server Backend (Firebase/Cloud)

1. **Deploy to Firebase Functions:**
   ```bash
   cd server-backend
   firebase init functions
   firebase deploy --only functions
   ```

2. **Update client configuration:**
   ```python
   # client-backend/config.py
   SERVER_URL = "wss://your-firebase-project.web.app"
   ```

### Client Backend (Local Installation)

1. **Create system service (Linux/macOS):**
   ```bash
   sudo cp drivertc-client.service /etc/systemd/system/
   sudo systemctl enable drivertc-client
   sudo systemctl start drivertc-client
   ```

2. **Auto-start on boot:**
   - macOS: Use LaunchDaemon
   - Windows: Use Windows Service
   - Linux: Use systemd service

### Frontend (Web Hosting)

1. **Build for production:**
   ```bash
   cd frontend
   npm run build
   ```

2. **Deploy to hosting service:**
   - Netlify: `netlify deploy --prod --dir=build`
   - Vercel: `vercel --prod`
   - Firebase: `firebase deploy --only hosting`

## Configuration

### Environment Variables

**Server Backend:**
- `PORT`: Server port (default: 8000)
- `CORS_ORIGINS`: Allowed CORS origins

**Client Backend:**
- `DRIVERTC_SERVER_URL`: WebSocket server URL
- `DRIVERTC_SHARED_FOLDER`: Shared folder path
- `DRIVERTC_CHUNK_SIZE`: File chunk size in bytes
- `DRIVERTC_MAX_TRANSFERS`: Max concurrent transfers

**Frontend:**
- `REACT_APP_CLIENT_BACKEND_URL`: Client backend URL

### Firewall Configuration

Open the following ports:
- **8000**: Server backend (WebSocket signaling)
- **8001**: Client backend (HTTP API)
- **3000**: Frontend (development only)

### Network Requirements

- **STUN/TURN servers**: For WebRTC NAT traversal
- **Port forwarding**: May be required for direct P2P connections
- **Firewall rules**: Allow WebRTC traffic (UDP ports)

## Security Considerations

1. **Authentication**: Implement user authentication for production
2. **File access**: Restrict shared folder permissions
3. **Network security**: Use HTTPS/WSS in production
4. **File validation**: Validate uploaded files
5. **Rate limiting**: Implement transfer rate limits

## Monitoring

### Health Checks

- Server: `GET /health`
- Client: `GET /`

### Logging

Logs are written to:
- Server: stdout/stderr
- Client: stdout/stderr + file logs
- Frontend: Browser console

### Metrics

Monitor:
- Active connections
- Transfer speeds
- Error rates
- Storage usage
