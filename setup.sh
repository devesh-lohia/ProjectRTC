#!/bin/bash

# DriveRTC Setup Script

echo "🚀 Setting up DriveRTC File Sharing System..."

# Create shared directories
echo "📁 Creating shared directories..."
mkdir -p ~/DriveRTC_Shared
mkdir -p ~/DriveRTC_Shared/.temp
mkdir -p ~/DriveRTC_Shared/received

# Install server backend dependencies
echo "🔧 Installing server backend dependencies..."
cd server-backend
pip install -r requirements.txt
cd ..

# Install client backend dependencies
echo "🔧 Installing client backend dependencies..."
cd client-backend
pip install -r requirements.txt
cd ..

# Install frontend dependencies
echo "🔧 Installing frontend dependencies..."
cd frontend
npm install
cd ..

echo "✅ Setup complete!"
echo ""
echo "⚙️  Configuration:"
echo "Run './config.sh' to configure server addresses for your deployment"
echo ""
echo "🎯 To start the system:"
echo "1. Start server backend: cd server-backend && python3 main.py"
echo "2. Start client backend: cd client-backend && python3 main.py"
echo "3. Start frontend: cd frontend && npm start"
echo ""
echo "🌐 Access the web interface at: http://localhost:3000"
echo "📂 Shared folder location: ~/DriveRTC_Shared"
echo ""
echo "💡 For production deployment, see DEPLOYMENT.md"
