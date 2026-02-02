from datetime import datetime
from typing import Any
from bson import ObjectId

def serialize_doc(doc: Any) -> Any:
    """
    Recursively convert MongoDB document or list of documents
    to JSON-serializable format:
      - ObjectId -> str
      - datetime -> ISO string
      - Handles nested objects and lists
    """
    if doc is None:
        return None
    
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    
    if isinstance(doc, dict):
        serialized = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                serialized[key] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            elif isinstance(value, (dict, list)):
                serialized[key] = serialize_doc(value)
            elif isinstance(value, bytes):
                # Handle binary data if needed
                serialized[key] = value.decode('utf-8', errors='ignore')
            else:
                serialized[key] = value
        return serialized
    
    # Handle standalone ObjectId or datetime
    if isinstance(doc, ObjectId):
        return str(doc)
    
    if isinstance(doc, datetime):
        return doc.isoformat()
    
    # Return as-is for primitives (str, int, float, bool, etc.)
    return doc