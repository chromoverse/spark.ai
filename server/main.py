# main.py
import uvicorn
from app.config import settings

from dotenv import load_dotenv
load_dotenv()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=True)