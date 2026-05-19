# SPARK - AI Assistant Architecture
## Electron Client + FastAPI Server Documentation

---

## 📋 Table of Contents
1. [Overview](#overview)
2. [Electron Client](#electron-client)
3. [FastAPI Server](#fastapi-server)
4. [System Architecture](#system-architecture)
5. [Communication Flow](#communication-flow)
6. [Key Technologies](#key-technologies)

---

## Overview

**SPARK** is an AI-powered voice assistant built on a **3-tier architecture**:

| Component | Role | Type |
|-----------|------|------|
| **Electron App** | User interface, local audio playback | Desktop App (React + TypeScript) |
| **FastAPI Server** | Backend orchestration, AI/ML processing | HTTP + WebSocket (Python) |
| **Voice Daemon** | Microphone capture, wake-word detection | System Service (Python) |

The system ensures **always-on availability** — even when the screen is locked or before user login.

---

## Electron Client

### 📁 Directory Structure
```
electron/
├── src/
│   ├── main/              # Electron main process (IPC, windows, services)
│   │   ├── main.ts        # Entry point, window creation
│   │   ├── preload.cts    # Security context bridge
│   │   ├── ipc/           # Inter-process communication handlers
│   │   ├── services/      # System integration services
│   │   ├── windows/       # Window management
│   │   └── utils/         # Helper utilities
│   │
│   ├── renderer/          # React UI (main rendering process)
│   │   ├── App.tsx        # Root component
│   │   ├── pages/         # Page components (login, chat, settings)
│   │   ├── components/    # Reusable UI components
│   │   ├── hooks/         # React custom hooks
│   │   ├── context/       # Context API state management
│   │   ├── store/         # Redux store (global state)
│   │   ├── utils/         # UI utilities
│   │   └── lib/           # Shared libraries
│   │
│   ├── types/             # TypeScript type definitions
│   ├── assets/            # Static resources
│   └── resources/         # Build resources
│
├── dist-electron/        # Compiled main process
├── dist-react/          # Built React app
├── public/              # Static public assets
├── action_executor/     # Python action execution bridge
├── python-service/      # Python services communication
├── testing/             # Test files
│
├── package.json         # Dependencies & scripts
├── tsconfig.json        # TypeScript configuration
├── vite.config.ts       # Vite build configuration
├── electron-builder.json # Build distribution config
├── eslint.config.js     # Code linting rules
└── stt.toml            # Speech-to-Text configuration
```

### 🎯 Key Features

#### **Main Process** (`src/main/`)
- **Window Management**: Creates and manages Electron windows
- **IPC Communication**: Handles inter-process communication with renderer
- **System Integration**: Integrates with OS (tray, shortcuts, etc.)
- **Preload Security**: Provides secure context bridge to renderer

#### **Renderer (UI)** (`src/renderer/`)
- **Authentication**: Login/Registration flow with OTP verification
- **Chat Interface**: Real-time messaging with the AI
- **Voice Control**: Trigger and manage voice interactions
- **Settings Panel**: User preferences and configurations
- **Redux Store**: Centralized state management for:
  - User authentication status
  - Chat history
  - Server connection state
  - UI preferences

#### **Python Bridge** (`action_executor/`)
- Executes Python actions from the Electron app
- Handles tool invocations
- Manages Python subprocess execution
- Provides a bridge to Python-based capabilities

### 📦 Key Dependencies

**Frontend Stack:**
- **React 19**: UI framework
- **TypeScript**: Type-safe JavaScript
- **Vite**: Build tool (fast HMR)
- **Tailwind CSS**: Styling
- **Redux Toolkit**: State management
- **Socket.IO Client**: Real-time WebSocket communication
- **Radix UI**: Accessible UI components
- **Lucide React**: Icon library
- **Next-themes**: Dark mode support

**Desktop Integration:**
- **Electron**: Cross-platform desktop app framework
- **Electron Builder**: Distribution & packaging
- **Keytar**: Secure credential storage
- **VAD Web**: Voice Activity Detection

### 🔧 Build & Development

```bash
# Development
npm run dev           # Start dev server + electron in development
npm run dev:react    # Vite dev server only
npm run dev:electron # Electron development mode

# Production Build
npm run build        # Transpile TS + Build React + Create distribution
npm run dist:win    # Build Windows executable
npm run dist:mac    # Build macOS app
npm run dist:linux  # Build Linux AppImage

# Other Commands
npm run lint        # Check code style
npm run preview     # Preview production build
npm run transpile:electron # Compile TypeScript for main process
```

### 🔐 Security
- **Preload Scripts**: Isolate renderer from Node.js
- **Context Bridge**: Controlled API exposure to renderer
- **Keytar Integration**: Secure token storage (system keyring)
- **Token Management**: Auto-refresh with interceptors

---

## FastAPI Server

### 📁 Directory Structure
```
server/
├── app/
│   ├── main.py              # FastAPI app initialization
│   ├── config.py            # Configuration & environment
│   ├── auto_initializer.py  # Auto-setup on startup
│   ├── startup_registrations.py # Initialize services
│   ├── startup_state.py     # Maintain startup state
│   │
│   ├── api/                 # HTTP endpoints
│   │   ├── auth/           # Authentication routes
│   │   ├── chat/           # Chat/conversation routes
│   │   ├── tools/          # Tool execution routes
│   │   └── health/         # Health check routes
│   │
│   ├── socket/              # WebSocket handlers
│   │   ├── events.py       # Socket.IO event handlers
│   │   ├── namespaces.py   # Socket namespace definitions
│   │   └── handlers/       # Event-specific handlers
│   │
│   ├── ai/                  # AI/ML Intelligence
│   │   ├── llm/            # LLM integration (Groq, OpenRouter)
│   │   ├── stt/            # Speech-to-Text (Groq/Gladia)
│   │   ├── tts/            # Text-to-Speech generation
│   │   ├── rag/            # RAG pipeline
│   │   └── agents/         # AI agent orchestration
│   │
│   ├── agent/               # Agent Logic
│   │   ├── core/           # Agent engine
│   │   ├── tools/          # Tool execution
│   │   ├── memory/         # Conversation memory
│   │   └── reasoning/      # Decision logic
│   │
│   ├── services/            # Core Services
│   │   ├── auth_service.py # Token & authentication
│   │   ├── user_service.py # User management
│   │   ├── cache_service.py # Redis caching
│   │   ├── email_service.py # Email sending
│   │   └── tool_service.py  # Tool registry & execution
│   │
│   ├── db/                  # Database Layer
│   │   ├── mongodb/        # MongoDB models & queries
│   │   ├── redis/          # Redis client & helpers
│   │   └── migrations/     # DB schema changes
│   │
│   ├── models/              # Data Models
│   │   ├── user.py         # User schema
│   │   ├── conversation.py # Chat history schema
│   │   ├── tool.py         # Tool definitions
│   │   └── state.py        # Session state schema
│   │
│   ├── schemas/             # Pydantic request/response schemas
│   │   ├── auth.py         # Auth DTOs
│   │   ├── chat.py         # Chat DTOs
│   │   └── tool.py         # Tool DTOs
│   │
│   ├── controllers/         # Business Logic Controllers
│   │   ├── auth_controller.py
│   │   ├── chat_controller.py
│   │   ├── tool_controller.py
│   │   └── rag_controller.py
│   │
│   ├── features/            # Feature Modules
│   │   ├── email_verification/
│   │   ├── oauth_integration/
│   │   ├── tool_execution/
│   │   └── streaming_response/
│   │
│   ├── plugins/             # Plugin System
│   │   ├── tool_plugins/   # External tool integrations
│   │   └── model_plugins/  # LLM model plugins
│   │
│   ├── cache/               # Caching Layer
│   │   ├── query_cache.py  # Query result caching
│   │   └── session_cache.py # Session caching
│   │
│   ├── kernel/              # Core Execution Engine
│   │   ├── executor.py     # Task executor
│   │   ├── scheduler.py    # Job scheduling
│   │   └── queue.py        # Task queue
│   │
│   ├── utils/               # Utility Functions
│   │   ├── validators.py   # Input validation
│   │   ├── formatters.py   # Response formatting
│   │   └── helpers.py      # General helpers
│   │
│   ├── prompts/             # AI Prompts
│   │   ├── system.py       # System prompts
│   │   ├── templates.py    # Prompt templates
│   │   └── instructions/   # Specialized instructions
│   │
│   ├── jwt/                 # JWT Token Management
│   │   ├── encoder.py      # Token creation
│   │   └── decoder.py      # Token validation
│   │
│   ├── helper/              # Helper Modules
│   ├── bootstrap/           # Bootstrap utilities
│   ├── dependencies/        # Dependency injection
│   └── ml/                  # ML Models & Processing
│
├── llm_models/              # Local ML Models
│   ├── bge-m3/             # Embedding model
│   ├── faster-whisper-small/ # STT model
│   ├── emotion-roberta/    # Emotion detection
│   └── kokoro/             # TTS model
│
├── scripts/                 # Utility Scripts
│   ├── download_models.py  # Download/cache models
│   ├── encrypt_secrets.py  # Encrypt credentials
│   ├── migrate_storage_layout.py # DB migrations
│   ├── prod_start.sh       # Production startup
│   └── tools_script_wrapper.py # Tool execution wrapper
│
├── public/                  # Static files
│   └── voices/             # Voice files
│
├── main.py                  # Server entry point
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Docker orchestration
├── Dockerfile              # Container image
├── env.sample              # Environment template
├── credentials.json        # OAuth credentials
└── token.json             # Cached tokens
```

### 🎯 Key Features

#### **Authentication & Security**
- **Passwordless Auth**: Email + OTP verification
- **JWT Tokens**: Access + Refresh token strategy
- **Token Rotation**: Secure refresh token rotation
- **Redis Session Management**: Distributed session caching
- **Auto-Refresh**: Seamless token refresh on client

#### **Real-Time Communication**
- **WebSocket via Socket.IO**: Stateful AI conversations
- **Event-Driven Architecture**: Pub/Sub pattern for messages
- **Connection Handshake**: JWT validation on connect
- **Automatic Reconnection**: Client-side reconnect logic

#### **AI Intelligence**
- **STT (Speech-to-Text)**: Groq/Gladia audio transcription
- **LLM Integration**: Multiple LLM providers (Groq, OpenRouter, local)
- **RAG Pipeline**: Vector embeddings + semantic search
- **TTS (Text-to-Speech)**: Generate natural speech
- **Agent Orchestration**: Multi-step reasoning & task execution

#### **Data Management**
- **MongoDB**: Persistent user data, chat history, tool definitions
- **Redis**: Session caching, message queue, real-time state
- **Vector DB**: Embedding storage for RAG

#### **Tool System**
- **Tool Registry**: Dynamic tool registration & discovery
- **Tool Execution**: Safe execution of tools with sandboxing
- **Tool Plugins**: Extensible plugin architecture
- **Permission System**: Fine-grained access control

### 📦 Key Dependencies

**Web Framework:**
- **FastAPI**: Modern async Python web framework
- **Socket.IO**: Real-time bidirectional communication
- **Pydantic**: Data validation & serialization

**AI/ML:**
- **Groq API**: Fast LLM inference
- **Hugging Face**: Model hub for embeddings/STT/TTS
- **Faster Whisper**: Optimized speech recognition
- **OpenWakeWord**: Wake word detection

**Data:**
- **MongoDB**: Document database
- **Redis**: In-memory cache & session store
- **Sqlalchemy**: ORM (if using SQL)

**Authentication:**
- **PyJWT**: JWT token handling
- **Bcrypt**: Password hashing
- **Email-validator**: Email validation

**Utils:**
- **Google Auth**: OAuth integration
- **HTTPX**: Async HTTP client
- **Pydantic-settings**: Configuration management

### 🚀 Deployment

#### **Local Development**
```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp env.sample .env
# Edit .env with API keys and database URLs

# Run server
python main.py
```

#### **Docker Deployment**
```bash
# Build and run with Docker Compose
docker-compose up --build

# Components started:
# - FastAPI Server: port 8000
# - Redis: port 6379
# - MongoDB: port 27017
```

#### **Production**
- Deploy via Docker Compose or Kubernetes
- Use nginx as reverse proxy
- Enable HTTPS/WSS
- Configure environment variables
- Run migrations with scripts/

### 🔌 API Endpoints

#### **Authentication**
- `POST /auth/register` — Register new user
- `POST /auth/verify-otp` — Verify email OTP
- `POST /auth/refresh-token` — Refresh access token
- `POST /auth/logout` — Logout user

#### **Chat**
- `POST /chat/send` — Send text message
- `WebSocket /socket` — Real-time chat via Socket.IO

#### **Tools**
- `GET /tools` — List available tools
- `POST /tools/{tool_id}/execute` — Execute a tool
- `GET /tools/{tool_id}` — Get tool details

#### **RAG**
- `POST /rag/search` — Search knowledge base
- `POST /rag/upload` — Upload documents

---

## System Architecture

### 🔄 3-Tier Process Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Operating System                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐    ┌──────────────┐  ┌────────────┐ │
│  │   FastAPI    │    │ Voice Daemon │  │ Electron   │ │
│  │   Server     │    │              │  │ App        │ │
│  │ :8000        │    │ (System Svc) │  │ (User)     │ │
│  │              │◄──►│              │  │            │ │
│  │ - STT        │    │ - Mic Listen │  │ - UI       │ │
│  │ - LLM        │    │ - Wake Word  │  │ - WebSocket│ │
│  │ - TTS        │    │ - VAD        │  │ - Audio    │ │
│  │ - RAG        │    │ - Audio Out  │  │ - IPC      │ │
│  │ - Tools      │    │              │  │            │ │
│  └──────────────┘    └──────────────┘  └────────────┘ │
│       │                                       │         │
│       └───────────────┬───────────────────────┘         │
│                       │                                  │
│  ┌────────────────────┴─────────────────────┐           │
│  │  ┌─────────────┐  ┌──────────────────┐  │           │
│  │  │  MongoDB    │  │     Redis        │  │           │
│  │  │  Database   │  │     Cache        │  │           │
│  │  │             │  │     + Sessions   │  │           │
│  │  └─────────────┘  └──────────────────┘  │           │
│  └────────────────────────────────────────┘           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 📡 Communication Patterns

#### **Electron ↔ Server**
- **HTTP**: Authentication, REST queries
- **WebSocket (Socket.IO)**: Real-time chat, streaming responses
- **Local IPC**: Electron main ↔ renderer process

#### **Voice Daemon ↔ Server**
- **HTTP/WebSocket**: Audio streaming, wake-word events
- **Events**: Mic activation, error reporting

#### **Server Internal**
- **Redis Pub/Sub**: Event distribution
- **MongoDB Transactions**: Atomic operations
- **Task Queue**: Background job processing

---

## Communication Flow

### 🎤 Voice Interaction Flow

```
1. USER SPEAKS
   │
   └──► Daemon detects wake word (OpenWakeWord)
        │
        └──► Plays "ding.wav" confirmation
             │
             └──► Captures audio + VAD (Silero)
                  │
                  └──► Streams audio chunks to Server
                       │
                       ├──► Server: Groq STT → Transcript
                       │
                       ├──► RAG: Vector search + context
                       │
                       ├──► LLM: Generate response (streaming)
                       │
                       ├──► TTS: Generate speech audio
                       │
                       └──► WebSocket: Send to Electron
                            │
                            ├──► Display transcript
                            ├──► Show response
                            └──► Play audio (if screen unlocked)
```

### 🔐 Authentication Flow

```
1. Client: POST /auth/register {email}
   │
   └──► Server: Generate OTP → Send email
        │
        └──► Client: POST /auth/verify-otp {email, otp}
             │
             └──► Server: Validate OTP
                  │
                  └──► Return {access_token, refresh_token}
                       │
                       └──► Client: Store tokens (Keytar)
                            │
                            └──► Connect WebSocket with JWT
```

---

## Key Technologies

### **Frontend (Electron)**
| Tech | Purpose |
|------|---------|
| React 19 | UI rendering & state management |
| TypeScript | Type-safe development |
| Vite | Fast build & HMR |
| Tailwind CSS | Responsive styling |
| Redux Toolkit | Centralized app state |
| Socket.IO Client | Real-time WebSocket |

### **Backend (Server)**
| Tech | Purpose |
|------|---------|
| FastAPI | High-performance HTTP/WebSocket framework |
| Python 3.11+ | Core language |
| SQLAlchemy | ORM for database access |
| Pydantic | Data validation |
| Socket.IO | Real-time event streaming |

### **AI/ML**
| Component | Provider |
|-----------|----------|
| LLM | Groq / OpenRouter |
| STT | Groq / Gladia / Faster Whisper |
| TTS | Kokoro / Edge-TTS / Google |
| Embeddings | BGE-M3 (local) |
| RAG | Vector search + semantic ranking |

### **Infrastructure**
| Service | Purpose |
|---------|---------|
| MongoDB | Persistent storage |
| Redis | Session cache & pub/sub |
| Docker | Containerization |
| Nginx | Reverse proxy (production) |

---

## Quick Reference

### Start Development
```bash
# Terminal 1: Server
cd server && python main.py

# Terminal 2: Voice Daemon  
cd voice_daemon && python main.py

# Terminal 3: Electron
cd electron && npm run dev
```

### Environment Variables
- `GROQ_API_KEY` — LLM inference
- `MONGO_URI` — Database connection
- `REDIS_URL` — Cache connection
- `JWT_SECRET` — Token signing key
- `OPENROUTER_API_KEY` — Fallback LLM

### Documentation References
- [Server Detailed Docs](server/README.md)
- [Electron Docs](electron/README.md)
- [Architecture Detail](PRODUCTION.md)
- [Latency Analysis](docs/latency.md)

---

*Last Updated: May 2026*
*Built by Chromoverse*
