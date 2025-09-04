#!/bin/bash

# DriveRTC Configuration Script
# This script helps configure server addresses for different deployment scenarios

echo "🔧 DriveRTC Configuration Helper"
echo "================================"

# Function to update client backend config
update_client_config() {
    local server_url=$1
    local config_file="client-backend/config.py"
    
    # Backup original
    cp "$config_file" "$config_file.backup"
    
    # Update SERVER_URL
    sed -i.tmp "s|SERVER_URL = .*|SERVER_URL = \"$server_url\"|g" "$config_file"
    sed -i.tmp "s|SERVER_HTTP_URL = .*|SERVER_HTTP_URL = \"${server_url/ws/http}\"|g" "$config_file"
    
    rm "$config_file.tmp"
    echo "✅ Updated client backend config"
}

# Function to create environment file
create_env_file() {
    local server_url=$1
    local client_url=$2
    
    cat > .env << EOF
# DriveRTC Configuration
DRIVERTC_SERVER_URL=$server_url
DRIVERTC_SERVER_HTTP_URL=${server_url/ws/http}
REACT_APP_CLIENT_BACKEND_URL=$client_url
DRIVERTC_SHARED_FOLDER=~/DriveRTC_Shared
DRIVERTC_CHUNK_SIZE=1048576
EOF
    echo "✅ Created .env file"
}

echo ""
echo "Select deployment scenario:"
echo "1) Local development (localhost)"
echo "2) Production with custom server URL"
echo "3) Firebase deployment"
echo ""
read -p "Enter choice (1-3): " choice

case $choice in
    1)
        echo "🏠 Configuring for local development..."
        SERVER_URL="ws://localhost:8000"
        CLIENT_URL="http://localhost:8001"
        ;;
    2)
        read -p "Enter your server WebSocket URL (e.g., wss://your-domain.com): " SERVER_URL
        CLIENT_URL="http://localhost:8001"
        ;;
    3)
        read -p "Enter your Firebase project URL (e.g., your-project.web.app): " FIREBASE_URL
        SERVER_URL="wss://$FIREBASE_URL"
        CLIENT_URL="http://localhost:8001"
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "📝 Configuration Summary:"
echo "Server URL: $SERVER_URL"
echo "Client URL: $CLIENT_URL"
echo ""

read -p "Apply this configuration? (y/N): " confirm
if [[ $confirm =~ ^[Yy]$ ]]; then
    update_client_config "$SERVER_URL"
    create_env_file "$SERVER_URL" "$CLIENT_URL"
    
    echo ""
    echo "✅ Configuration applied successfully!"
    echo ""
    echo "📋 Next steps:"
    echo "1. Start server backend: cd server-backend && python3 main.py"
    echo "2. Start client backend: cd client-backend && python3 main.py"
    echo "3. Start frontend: cd frontend && npm start"
    echo ""
    echo "🌐 Frontend will connect to: $CLIENT_URL"
    echo "🔗 Client will connect to server: $SERVER_URL"
else
    echo "❌ Configuration cancelled"
fi
