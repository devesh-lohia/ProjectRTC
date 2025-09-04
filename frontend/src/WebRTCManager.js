/**
 * WebRTC Manager for P2P file transfers
 * Handles WebRTC connections, signaling, and data channels
 */

class WebRTCManager {
    constructor(serverUrl, clientBackendUrl) {
        this.serverUrl = serverUrl;
        this.clientBackendUrl = clientBackendUrl;
        this.localPeerId = null;
        this.peerConnections = new Map();
        this.dataChannels = new Map();
        this.signalingSocket = null;
        this.isConnected = false;
        
        // WebRTC configuration
        this.rtcConfig = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ]
        };
        
        // Event handlers
        this.onPeerConnected = null;
        this.onPeerDisconnected = null;
        this.onDataReceived = null;
        this.onTransferProgress = null;
    }
    
    async initialize() {
        try {
            // Connect to server backend for signaling
            await this.connectToSignalingServer();
            console.log('WebRTC Manager initialized');
            return true;
        } catch (error) {
            console.error('Failed to initialize WebRTC Manager:', error);
            return false;
        }
    }
    
    async connectToSignalingServer() {
        return new Promise((resolve, reject) => {
            const wsUrl = this.serverUrl.replace('https://', 'wss://').replace('http://', 'ws://');
            
            // Generate unique peer ID
            this.localPeerId = 'frontend-' + Math.random().toString(36).substr(2, 9);
            
            this.signalingSocket = new WebSocket(`${wsUrl}/ws/${this.localPeerId}`);
            
            this.signalingSocket.onopen = () => {
                console.log('Connected to signaling server');
                this.isConnected = true;
                
                // Register as frontend client
                this.sendSignalingMessage({
                    type: 'register',
                    device_name: `Frontend-${this.localPeerId.substr(-8)}`,
                    ip_address: window.location.hostname,
                    local_port: window.location.port || 3000
                });
                
                resolve();
            };
            
            this.signalingSocket.onmessage = (event) => {
                this.handleSignalingMessage(JSON.parse(event.data));
            };
            
            this.signalingSocket.onerror = (error) => {
                console.error('Signaling socket error:', error);
                reject(error);
            };
            
            this.signalingSocket.onclose = () => {
                console.log('Signaling connection closed');
                this.isConnected = false;
            };
        });
    }
    
    sendSignalingMessage(message) {
        if (this.signalingSocket && this.isConnected) {
            this.signalingSocket.send(JSON.stringify(message));
        }
    }
    
    async handleSignalingMessage(message) {
        console.log('Received signaling message:', message);
        
        switch (message.type) {
            case 'registration_success':
                console.log('Successfully registered with signaling server');
                break;
                
            case 'offer':
                await this.handleOffer(message.from_client, message.data);
                break;
                
            case 'answer':
                await this.handleAnswer(message.from_client, message.data);
                break;
                
            case 'ice_candidate':
                await this.handleIceCandidate(message.from_client, message.data);
                break;
                
            case 'client_list_update':
                // Handle updated client list
                if (this.onPeerListUpdate) {
                    this.onPeerListUpdate(message.clients);
                }
                break;
                
            default:
                console.log('Unknown signaling message type:', message.type);
        }
    }
    
    async createPeerConnection(peerId) {
        const peerConnection = new RTCPeerConnection(this.rtcConfig);
        
        // Handle ICE candidates
        peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                this.sendSignalingMessage({
                    type: 'ice_candidate',
                    to_client: peerId,
                    data: event.candidate
                });
            }
        };
        
        // Handle connection state changes
        peerConnection.onconnectionstatechange = () => {
            console.log(`Peer connection state: ${peerConnection.connectionState}`);
            
            if (peerConnection.connectionState === 'connected') {
                if (this.onPeerConnected) {
                    this.onPeerConnected(peerId);
                }
            } else if (peerConnection.connectionState === 'disconnected' || 
                       peerConnection.connectionState === 'failed') {
                if (this.onPeerDisconnected) {
                    this.onPeerDisconnected(peerId);
                }
                this.cleanupPeerConnection(peerId);
            }
        };
        
        // Handle incoming data channels
        peerConnection.ondatachannel = (event) => {
            const channel = event.channel;
            this.setupDataChannel(channel, peerId);
        };
        
        this.peerConnections.set(peerId, peerConnection);
        return peerConnection;
    }
    
    setupDataChannel(channel, peerId) {
        channel.onopen = () => {
            console.log(`Data channel opened with ${peerId}`);
        };
        
        channel.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (this.onDataReceived) {
                    this.onDataReceived(peerId, data);
                }
            } catch (error) {
                console.error('Error parsing data channel message:', error);
            }
        };
        
        channel.onerror = (error) => {
            console.error(`Data channel error with ${peerId}:`, error);
        };
        
        channel.onclose = () => {
            console.log(`Data channel closed with ${peerId}`);
        };
        
        this.dataChannels.set(peerId, channel);
    }
    
    async initiateConnection(peerId) {
        try {
            const peerConnection = await this.createPeerConnection(peerId);
            
            // Create data channel for file transfers
            const dataChannel = peerConnection.createDataChannel('fileTransfer', {
                ordered: true
            });
            this.setupDataChannel(dataChannel, peerId);
            
            // Create offer
            const offer = await peerConnection.createOffer();
            await peerConnection.setLocalDescription(offer);
            
            // Send offer through signaling server
            this.sendSignalingMessage({
                type: 'offer',
                to_client: peerId,
                data: offer
            });
            
            return true;
        } catch (error) {
            console.error('Failed to initiate connection:', error);
            return false;
        }
    }
    
    async handleOffer(peerId, offer) {
        try {
            const peerConnection = await this.createPeerConnection(peerId);
            
            await peerConnection.setRemoteDescription(offer);
            
            // Create answer
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);
            
            // Send answer through signaling server
            this.sendSignalingMessage({
                type: 'answer',
                to_client: peerId,
                data: answer
            });
        } catch (error) {
            console.error('Failed to handle offer:', error);
        }
    }
    
    async handleAnswer(peerId, answer) {
        try {
            const peerConnection = this.peerConnections.get(peerId);
            if (peerConnection) {
                await peerConnection.setRemoteDescription(answer);
            }
        } catch (error) {
            console.error('Failed to handle answer:', error);
        }
    }
    
    async handleIceCandidate(peerId, candidate) {
        try {
            const peerConnection = this.peerConnections.get(peerId);
            if (peerConnection) {
                await peerConnection.addIceCandidate(candidate);
            }
        } catch (error) {
            console.error('Failed to handle ICE candidate:', error);
        }
    }
    
    sendDataToPeer(peerId, data) {
        const channel = this.dataChannels.get(peerId);
        if (channel && channel.readyState === 'open') {
            channel.send(JSON.stringify(data));
            return true;
        }
        return false;
    }
    
    async transferFileToPeer(peerId, fileData) {
        try {
            // Send file metadata first
            const metadata = {
                type: 'file_metadata',
                name: fileData.name,
                size: fileData.size,
                chunks: Math.ceil(fileData.size / 16384) // 16KB chunks
            };
            
            if (!this.sendDataToPeer(peerId, metadata)) {
                throw new Error('Failed to send file metadata');
            }
            
            // Send file in chunks
            const chunkSize = 16384;
            const totalChunks = Math.ceil(fileData.size / chunkSize);
            
            for (let i = 0; i < totalChunks; i++) {
                const start = i * chunkSize;
                const end = Math.min(start + chunkSize, fileData.size);
                const chunk = fileData.slice(start, end);
                
                // Convert chunk to base64 for transmission
                const reader = new FileReader();
                const chunkData = await new Promise((resolve) => {
                    reader.onload = () => resolve(reader.result.split(',')[1]);
                    reader.readAsDataURL(chunk);
                });
                
                const chunkMessage = {
                    type: 'file_chunk',
                    chunk_index: i,
                    total_chunks: totalChunks,
                    data: chunkData
                };
                
                if (!this.sendDataToPeer(peerId, chunkMessage)) {
                    throw new Error(`Failed to send chunk ${i}`);
                }
                
                // Report progress
                if (this.onTransferProgress) {
                    this.onTransferProgress({
                        peerId,
                        fileName: fileData.name,
                        progress: ((i + 1) / totalChunks) * 100
                    });
                }
                
                // Small delay to prevent overwhelming the data channel
                await new Promise(resolve => setTimeout(resolve, 10));
            }
            
            // Send completion message
            this.sendDataToPeer(peerId, {
                type: 'transfer_complete',
                fileName: fileData.name
            });
            
            return true;
        } catch (error) {
            console.error('File transfer failed:', error);
            return false;
        }
    }
    
    cleanupPeerConnection(peerId) {
        const peerConnection = this.peerConnections.get(peerId);
        if (peerConnection) {
            peerConnection.close();
            this.peerConnections.delete(peerId);
        }
        
        const dataChannel = this.dataChannels.get(peerId);
        if (dataChannel) {
            dataChannel.close();
            this.dataChannels.delete(peerId);
        }
    }
    
    disconnect() {
        // Close all peer connections
        for (const [peerId] of this.peerConnections) {
            this.cleanupPeerConnection(peerId);
        }
        
        // Close signaling connection
        if (this.signalingSocket) {
            this.signalingSocket.close();
            this.signalingSocket = null;
        }
        
        this.isConnected = false;
    }
}

export default WebRTCManager;
