import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { 
  Folder, 
  File, 
  Download, 
  Copy, 
  Trash2, 
  FolderOpen, 
  ArrowLeft,
  Monitor,
  Wifi,
  WifiOff,
  Upload,
  Clipboard
} from 'lucide-react';
import WebRTCManager from './WebRTCManager';
import './App.css';

const CLIENT_BACKEND_URL = process.env.REACT_APP_CLIENT_BACKEND_URL || 'http://localhost:8001';
const SERVER_BACKEND_URL = process.env.REACT_APP_SERVER_BACKEND_URL || 'https://secret-bridie-drivertc-bbe7d7d5.koyeb.app';

function App() {
  const [devices, setDevices] = useState([]);
  const [currentDevice, setCurrentDevice] = useState(null);
  const [currentPath, setCurrentPath] = useState('');
  const [files, setFiles] = useState([]);
  const [selectedItems, setSelectedItems] = useState(new Set());
  const [clipboard, setClipboard] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [ws, setWs] = useState(null);
  const [loading, setLoading] = useState(false);
  const [localClientId, setLocalClientId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [localClientAvailable, setLocalClientAvailable] = useState(false);
  const [webrtcManager, setWebrtcManager] = useState(null);
  const [p2pConnections, setP2pConnections] = useState(new Map());
  const [transferProgress, setTransferProgress] = useState(new Map());

  // Fetch clients from server
  const fetchClientsFromServer = useCallback(async () => {
    try {
      const response = await axios.get(`${SERVER_BACKEND_URL}/clients`);
      const serverClients = response.data.clients;
      
      // Add local client if we have one
      const allDevices = [];
      if (localClientAvailable && localClientId) {
        allDevices.push({
          client_id: localClientId,
          device_name: 'This Device (Local)',
          status: 'online',
          isLocal: true,
          backend_url: CLIENT_BACKEND_URL,
          websocket_url: CLIENT_BACKEND_URL.replace('http', 'ws')
        });
      }
      
      // Add remote clients (exclude local client if it's already in server list)
      serverClients.forEach(client => {
        if (client.client_id !== localClientId) {
          allDevices.push({
            ...client,
            isLocal: false
          });
        }
      });
      
      setDevices(allDevices);
    } catch (error) {
      console.error('Failed to fetch clients from server:', error);
    }
  }, [localClientId, localClientAvailable]);

  // Initialize WebRTC Manager
  useEffect(() => {
    const initWebRTC = async () => {
      const manager = new WebRTCManager(SERVER_BACKEND_URL, CLIENT_BACKEND_URL);
      
      // Set up event handlers
      manager.onPeerConnected = (peerId) => {
        console.log(`P2P connection established with ${peerId}`);
        setP2pConnections(prev => new Map(prev.set(peerId, true)));
      };
      
      manager.onPeerDisconnected = (peerId) => {
        console.log(`P2P connection lost with ${peerId}`);
        setP2pConnections(prev => {
          const newMap = new Map(prev);
          newMap.delete(peerId);
          return newMap;
        });
      };
      
      manager.onTransferProgress = (progressInfo) => {
        setTransferProgress(prev => new Map(prev.set(progressInfo.peerId, progressInfo)));
      };
      
      manager.onDataReceived = (peerId, data) => {
        console.log(`Received data from ${peerId}:`, data);
        // Handle received file data
        if (data.type === 'file_metadata') {
          console.log(`Receiving file: ${data.name} (${data.size} bytes)`);
        } else if (data.type === 'file_chunk') {
          console.log(`Received chunk ${data.chunk_index + 1}/${data.total_chunks}`);
        } else if (data.type === 'transfer_complete') {
          console.log(`File transfer completed: ${data.fileName}`);
        }
      };
      
      // Initialize WebRTC connection
      const success = await manager.initialize();
      if (success) {
        setWebrtcManager(manager);
        console.log('WebRTC Manager initialized successfully');
      }
    };
    
    initWebRTC();
    
    return () => {
      if (webrtcManager) {
        webrtcManager.disconnect();
      }
    };
  }, []);

  // Check local client availability
  useEffect(() => {
    const checkLocalClient = async () => {
      try {
        await axios.get(`${CLIENT_BACKEND_URL}/`);
        setLocalClientAvailable(true);
        setLocalClientId('local-client-' + Date.now());
      } catch (error) {
        setLocalClientAvailable(false);
      }
    };
    
    checkLocalClient();
  }, []);

  // Check local client availability function
  const checkLocalClientAvailability = async () => {
    try {
      await axios.get(`${CLIENT_BACKEND_URL}/`);
      return true;
    } catch (error) {
      return false;
    }
  };

  // Initialize local client connection
  useEffect(() => {
    const initializeLocalClient = async () => {
      const isAvailable = await checkLocalClientAvailability();
      
      if (isAvailable) {
        // Try to establish WebSocket connection
        const wsUrl = CLIENT_BACKEND_URL.replace('http', 'ws');
        const websocket = new WebSocket(`${wsUrl}/ws`);
        
        websocket.onopen = () => {
          setIsConnected(true);
          setWs(websocket);
        };
        
        websocket.onmessage = (event) => {
          const data = JSON.parse(event.data);
          
          switch (data.type) {
            case 'client_info':
              // Store local client ID and fetch all clients from server
              setLocalClientId(data.client_id);
              break;
              
            case 'files_list':
              setFiles(data.data.files);
              setCurrentPath(data.data.current_path);
              setLoading(false);
              break;
              
            default:
              break;
          }
        };
        
        websocket.onclose = () => {
          setIsConnected(false);
          setWs(null);
          setLocalClientAvailable(false);
        };
        
        websocket.onerror = () => {
          setLocalClientAvailable(false);
        };
        
        return () => {
          websocket.close();
        };
      } else {
        console.log('Local client backend not available - running in remote-only mode');
      }
    };
    
    initializeLocalClient();
  }, [checkLocalClientAvailability]);

  // Fetch clients from server when localClientId is set
  useEffect(() => {
    if (localClientId) {
      fetchClientsFromServer();
      // Set up periodic refresh
      const interval = setInterval(fetchClientsFromServer, 5000); // Refresh every 5 seconds
      return () => clearInterval(interval);
    }
  }, [localClientId, fetchClientsFromServer]);

  const loadFiles = useCallback(async (path = '') => {
    if (!currentDevice) return;
    
    setLoading(true);
    
    if (currentDevice.isLocal && ws) {
      ws.send(JSON.stringify({
        type: 'get_files',
        path: path
      }));
    } else {
      // For remote devices, connect to their backend URL
      try {
        const response = await axios.get(`${currentDevice.backend_url}/files?path=${encodeURIComponent(path)}`);
        setFiles(response.data.files);
        setCurrentPath(response.data.current_path);
        setLoading(false);
      } catch (error) {
        console.error('Failed to load files from remote device:', error);
        setFiles([]);
        setCurrentPath(path);
        setLoading(false);
      }
    }
  }, [currentDevice, ws]);

  const handleDeviceSelect = (device) => {
    setCurrentDevice(device);
    setCurrentPath('');
    setSelectedItems(new Set());
    loadFiles('');
  };

  const handleItemClick = (item) => {
    const newSelected = new Set(selectedItems);
    if (newSelected.has(item.path)) {
      newSelected.delete(item.path);
    } else {
      newSelected.add(item.path);
    }
    setSelectedItems(newSelected);
  };

  const handleOpen = () => {
    const selectedArray = Array.from(selectedItems);
    if (selectedArray.length === 1) {
      const item = files.find(f => f.path === selectedArray[0]);
      if (item && item.is_directory) {
        const newPath = currentPath ? `${currentPath}/${item.name}` : item.name;
        loadFiles(newPath);
        setSelectedItems(new Set());
      }
    }
  };

  const handleBack = () => {
    if (currentPath) {
      const pathParts = currentPath.split('/');
      pathParts.pop();
      const newPath = pathParts.join('/');
      loadFiles(newPath);
    }
  };

  const handleDownload = async () => {
    if (!currentDevice || selectedItems.size === 0) return;
    
    const downloadUrl = currentDevice.isLocal ? CLIENT_BACKEND_URL : currentDevice.backend_url;
    
    for (const itemPath of selectedItems) {
      try {
        const response = await axios.get(
          `${downloadUrl}/download/${itemPath}`,
          { responseType: 'blob' }
        );
        
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', itemPath.split('/').pop());
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
      } catch (error) {
        console.error('Download failed:', error);
      }
    }
  };

  const handleCopy = () => {
    const selectedFiles = Array.from(selectedItems).map(path => 
      files.find(f => f.path === path)
    ).filter(Boolean);
    
    setClipboard(selectedFiles);
    setSelectedItems(new Set());
  };

  const handlePaste = async () => {
    if (clipboard.length === 0 || !currentDevice) return;
    
    // For local device, we'd implement actual file operations
    // For remote devices, this would trigger WebRTC transfer
    console.log('Pasting files:', clipboard);
    
    // Simulate paste operation
    setTimeout(() => {
      loadFiles(currentPath);
      setClipboard([]);
    }, 1000);
  };

  const handleDelete = async () => {
    if (!currentDevice || selectedItems.size === 0) return;
    
    const deleteUrl = currentDevice.isLocal ? CLIENT_BACKEND_URL : currentDevice.backend_url;
    
    if (window.confirm(`Delete ${selectedItems.size} item(s)?`)) {
      for (const itemPath of selectedItems) {
        try {
          await axios.delete(`${deleteUrl}/delete/${itemPath}`);
        } catch (error) {
          console.error('Delete failed:', error);
        }
      }
      setSelectedItems(new Set());
      loadFiles(currentPath);
    }
  };

  const handleUpload = async (event) => {
    if (!currentDevice) return;
    
    const files = event.target.files;
    if (!files || files.length === 0) return;
    
    setUploading(true);
    const uploadUrl = currentDevice.isLocal ? CLIENT_BACKEND_URL : currentDevice.backend_url;
    
    try {
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('path', currentPath);
        
        await axios.post(`${uploadUrl}/upload`, formData, {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        });
      }
      
      // Refresh file list after upload
      loadFiles(currentPath);
    } catch (error) {
      console.error('Upload failed:', error);
    } finally {
      setUploading(false);
      // Reset file input
      event.target.value = '';
    }
  };

  const getFileIcon = (file) => {
    return file.is_directory ? <Folder size={20} /> : <File size={20} />;
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '-';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>DriveRTC File Manager</h1>
        <div className="connection-status">
          {localClientAvailable ? (
            isConnected ? (
              <><Wifi size={16} /> Local Client Connected</>
            ) : (
              <><WifiOff size={16} /> Local Client Disconnected</>
            )
          ) : (
            <><Monitor size={16} /> Remote Only Mode</>
          )}
        </div>
      </header>

      <div className="app-content">
        <div className="sidebar">
          <h3>Devices</h3>
          <div className="devices-list">
            {devices.map(device => (
              <div
                key={device.client_id}
                className={`device-item ${currentDevice?.client_id === device.client_id ? 'active' : ''}`}
                onClick={() => handleDeviceSelect(device)}
              >
                <Monitor size={16} />
                <span>{device.device_name}</span>
                <div className={`status ${device.status}`}></div>
              </div>
            ))}
          </div>
        </div>

        <div className="main-content">
          {currentDevice ? (
            <>
              <div className="toolbar">
                <div className="navigation">
                  <button 
                    onClick={handleBack} 
                    disabled={!currentPath}
                    className="nav-button"
                  >
                    <ArrowLeft size={16} />
                  </button>
                  <span className="current-path">
                    {currentDevice.device_name} / {currentPath || 'Home'}
                  </span>
                </div>

                <div className="actions">
                  {selectedItems.size === 1 && files.find(f => f.path === Array.from(selectedItems)[0])?.is_directory && (
                    <button onClick={handleOpen} className="action-button">
                      <FolderOpen size={16} /> Open
                    </button>
                  )}
                  
                  {selectedItems.size > 0 && (
                    <>
                      <button onClick={handleDownload} className="action-button">
                        <Download size={16} /> Download
                      </button>
                      <button onClick={handleCopy} className="action-button">
                        <Copy size={16} /> Copy
                      </button>
                      <button onClick={handleDelete} className="action-button delete">
                        <Trash2 size={16} /> Delete
                      </button>
                    </>
                  )}
                  
                  {selectedItems.size === 0 && clipboard.length > 0 && (
                    <button onClick={handlePaste} className="action-button">
                      <Clipboard size={16} /> Paste ({clipboard.length})
                    </button>
                  )}
                  
                  {selectedItems.size === 0 && currentDevice && (
                    <>
                      <input
                        type="file"
                        id="file-upload"
                        multiple
                        onChange={handleUpload}
                        style={{ display: 'none' }}
                      />
                      <button 
                        onClick={() => document.getElementById('file-upload').click()}
                        className="action-button"
                        disabled={uploading}
                      >
                        <Upload size={16} /> {uploading ? 'Uploading...' : 'Upload'}
                      </button>
                    </>
                  )}
                </div>
              </div>

              <div className="files-container">
                {loading ? (
                  <div className="loading">Loading files...</div>
                ) : (
                  <div className="files-grid">
                    {files.map(file => (
                      <div
                        key={file.path}
                        className={`file-item ${selectedItems.has(file.path) ? 'selected' : ''}`}
                        onClick={() => handleItemClick(file)}
                        onDoubleClick={() => {
                          if (file.is_directory) {
                            const newPath = currentPath ? `${currentPath}/${file.name}` : file.name;
                            loadFiles(newPath);
                          }
                        }}
                      >
                        <div className="file-icon">
                          {getFileIcon(file)}
                        </div>
                        <div className="file-info">
                          <div className="file-name">{file.name}</div>
                          <div className="file-details">
                            {formatFileSize(file.size)} • {new Date(file.modified_time).toLocaleDateString()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="welcome">
              <h2>Select a device to browse files</h2>
              <p>Choose a device from the sidebar to start browsing and managing files.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
