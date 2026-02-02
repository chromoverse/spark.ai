# 🚀 Local Initialization Guide

This guide will help you set up and run the AI Assistant Server locally without using Docker.

## 📋 Prerequisites

*   **Python Version**: Python 3.11 or higher is required.
*   **Operating System**: Windows (as per current development environment), but compatible with Linux/macOS.
*   **Virtual Environment**: `venv` is recommended.

## ⚙️ Step-by-Step Setup

### 1. Create a Virtual Environment
Open your terminal in the project root and run:
```bash
python -m venv .venv
```

### 2. Activate the Virtual Environment
*   **Windows**:
    ```powershell
    .\.venv\Scripts\Activate.ps1
    ```
*   **Linux/macOS**:
    ```bash
    source .venv/bin/activate
    ```

### 3. Install Dependencies
Ensure you have `pip` updated and then install the required packages:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the `env.sample` file to a new file named `.env` and fill in your API keys and configuration:
```bash
cp env.sample .env
```
> [!IMPORTANT]
> Make sure to fill in all the required keys in `.env`, especially `MONGO_URI`, `UPSTASH_REDIS_REST_URL`, and relevant AI Model API keys (Gemini, OpenRouter, etc.).

### 5. Download ML Models (Optional/If applicable)
The project uses some local ML models. You may need to run the download script:
```bash
python scripts/download_models.py
```

### 6. Run the Server
You can start the server using `uvicorn`:
```bash
uvicorn main:app --reload --port 8000
```
Alternatively, if there is a startup script provided:
```bash
python main.py
```

## 🛠 Troubleshooting

*   **Python Version**: If `python` refers to an older version, try using `python3`.
*   **Missing Dependencies**: If you encounter "ModuleNotFoundError", ensure your virtual environment is activated and you have run `pip install -r requirements.txt`.
*   **Port Conflict**: If port 8000 is already in use, change the `PORT` in your `.env` file or specify a different port in the `uvicorn` command.

---
© 2026 SiddTheCoder.
