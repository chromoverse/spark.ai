# python-service/actions/apps/__init__.py
from .base import BaseApp
from .notepad import NotepadApp
from .vscode import VSCodeApp
from .chrome import ChromeApp
from .whatsapp import WhatsAppApp

__all__ = ['BaseApp', 'NotepadApp', 'VSCodeApp', 'ChromeApp', 'WhatsAppApp']