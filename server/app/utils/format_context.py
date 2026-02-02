from typing import List, Dict, Tuple
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

def format_context(recent_context: List[Dict], query_based_context: List[Dict]) -> Tuple[str, str]:
    """Format context data for prompt injection with timestamps and relative time."""
    
    now_nepal = datetime.now(NEPAL_TZ)
    
    # ---------------- Recent conversation ----------------
    if recent_context:
        recent_formatted = []
        for ctx in recent_context: 
            content = ctx.get('content', '')
            timestamp = ctx.get('timestamp', '')
            role = ctx.get('role', '')
            
            time_str = ""
            relative_time = ""
            
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        dt_utc = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        dt_nepal = dt_utc.astimezone(NEPAL_TZ)
                    else:
                        dt_utc = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC"))
                        dt_nepal = dt_utc.astimezone(NEPAL_TZ)
                    
                    time_str = dt_nepal.strftime('%b %d, %I:%M %p')
                    
                    time_diff = now_nepal - dt_nepal
                    minutes = int(time_diff.total_seconds() / 60)
                    
                    if minutes < 1:
                        relative_time = "just now"
                    elif minutes < 60:
                        relative_time = f"{minutes}m ago"
                    elif minutes < 1440:
                        hours = minutes // 60
                        relative_time = f"{hours}h ago"
                    else:
                        days = minutes // 1440
                        relative_time = f"{days}d ago"
                        
                except Exception:
                    time_str = "Unknown time"
                    relative_time = ""
            
            if relative_time:
                recent_formatted.append(f"[{time_str}] {content} ({relative_time}) - {role}")
            else:
                recent_formatted.append(f"[{time_str}] {content} - {role}")
        
        recent_str = "\n".join(recent_formatted)
    else:
        recent_str = "No recent conversation history."
    
    # ---------------- Query-based semantic context ----------------
    if query_based_context:
        query_formatted = []
        for ctx in query_based_context:
            # Try 'content' first as it is from redis, then 'query' as it is from pinecone
            query = ctx.get('content', '')
            if not query: query = ctx.get('query', '')
            relevance = ctx.get('score', 0)
            timestamp = ctx.get('timestamp', '')
            
            
            time_str = ""
            relative_time = ""
            
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        dt_utc = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        dt_nepal = dt_utc.astimezone(NEPAL_TZ)
                    else:
                        dt_utc = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC"))
                        dt_nepal = dt_utc.astimezone(NEPAL_TZ)
                    
                    time_str = dt_nepal.strftime('%b %d, %I:%M %p')
                    
                    time_diff = now_nepal - dt_nepal
                    minutes = int(time_diff.total_seconds() / 60)
                    
                    if minutes < 1:
                        relative_time = "just now"
                    elif minutes < 60:
                        relative_time = f"{minutes}m ago"
                    elif minutes < 1440:
                        hours = minutes // 60
                        relative_time = f"{hours}h ago"
                    else:
                        days = minutes // 1440
                        relative_time = f"{days}d ago"
                        
                except Exception:
                    time_str = "Unknown time"
                    relative_time = ""
            
            if relative_time:
                query_formatted.append(f"[{time_str}] {query} ({relative_time}) [rel:{relevance:.2f}]")
            else:
                query_formatted.append(f"[{time_str}] {query} [rel:{relevance:.2f}]")
        
        query_str = "\n".join(query_formatted)
    else:
        query_str = "No similar past queries found."
    
    return recent_str, query_str
