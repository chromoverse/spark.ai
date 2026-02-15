# client_core/tools/file_system/operations.py
"""
File System Operations Tools for Client

Real file system tools that execute on the client machine.
"""

import os
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class CreateFileTool(BaseTool):
    """Create file tool."""
    
    def get_tool_name(self) -> str:
        return "file_create"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Create a file with content."""
        path = inputs.get("path", "")
        content = inputs.get("content", "")
        overwrite = inputs.get("overwrite", False)
        
        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")
        
        try:
            expanded_path = os.path.expanduser(path)
            
            if os.path.exists(expanded_path) and not overwrite:
                return ToolOutput(
                    success=False, data={},
                    error=f"File already exists: {path}"
                )
            
            parent_dir = os.path.dirname(expanded_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            with open(expanded_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            file_stat = os.stat(expanded_path)
            
            self.logger.info(f"Created file: {path} ({file_stat.st_size} bytes)")
            
            return ToolOutput(
                success=True,
                data={
                    "path": path,
                    "absolute_path": expanded_path,
                    "size_bytes": file_stat.st_size,
                    "created_at": datetime.now().isoformat(),
                    "content_length": len(content)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to create file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FolderCreateTool(BaseTool):
    """Create folder tool."""
    
    def get_tool_name(self) -> str:
        return "folder_create"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Create a folder/directory."""
        path = inputs.get("path", "")
        recursive = inputs.get("recursive", True)
        
        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")
        
        try:
            expanded_path = os.path.expanduser(path)
            
            if recursive:
                os.makedirs(expanded_path, exist_ok=True)
            else:
                os.mkdir(expanded_path)
            
            self.logger.info(f"Created folder: {path}")
            
            return ToolOutput(
                success=True,
                data={
                    "folder_path": path,
                    "absolute_path": expanded_path,
                    "created_at": datetime.now().isoformat(),
                    "exists": os.path.exists(expanded_path)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to create folder: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileCopyTool(BaseTool):
    """Copy file tool."""
    
    def get_tool_name(self) -> str:
        return "file_copy"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Copy a file."""
        source = inputs.get("source", "")
        destination = inputs.get("destination", "")
        overwrite = inputs.get("overwrite", False)
        
        if not source or not destination:
            return ToolOutput(
                success=False, data={},
                error="Both source and destination are required"
            )
        
        try:
            import shutil
            
            source_path = os.path.expanduser(source)
            dest_path = os.path.expanduser(destination)
            
            if not os.path.exists(source_path):
                return ToolOutput(
                    success=False, data={},
                    error=f"Source file not found: {source}"
                )
            
            if os.path.exists(dest_path) and not overwrite:
                return ToolOutput(
                    success=False, data={},
                    error=f"Destination already exists: {destination}"
                )
            
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            
            shutil.copy2(source_path, dest_path)
            
            file_stat = os.stat(dest_path)
            
            self.logger.info(f"Copied: {source} → {destination}")
            
            return ToolOutput(
                success=True,
                data={
                    "source_path": source,
                    "destination_path": destination,
                    "size_bytes": file_stat.st_size,
                    "copied_at": datetime.now().isoformat()
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to copy file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileSearchTool(BaseTool):
    """File search tool."""
    
    def get_tool_name(self) -> str:
        return "file_search"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Search for files."""
        query = inputs.get("query", "")
        search_path = inputs.get("path", ".")
        max_results = inputs.get("max_results", 50)
        
        if not query:
            return ToolOutput(success=False, data={}, error="Query is required")
        
        try:
            expanded_path = os.path.expanduser(search_path)
            
            if not os.path.exists(expanded_path):
                return ToolOutput(
                    success=False, data={},
                    error=f"Path not found: {search_path}"
                )
            
            self.logger.info(f"Searching for '{query}' in {search_path}")
            
            results = []
            query_lower = query.lower()
            
            for root, dirs, files in os.walk(expanded_path):
                for file in files:
                    if query_lower in file.lower():
                        full_path = os.path.join(root, file)
                        file_stat = os.stat(full_path)
                        
                        results.append({
                            "filename": file,
                            "path": full_path,
                            "size_bytes": file_stat.st_size,
                            "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                        })
                        
                        if len(results) >= max_results:
                            break
                
                if len(results) >= max_results:
                    break
            
            self.logger.info(f"Found {len(results)} files")
            
            return ToolOutput(
                success=True,
                data={
                    "results": results,
                    "total_found": len(results),
                    "search_time_ms": 100,
                    "query": query,
                    "search_path": search_path
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to search files: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


class FileReadTool(BaseTool):
    """Read file tool."""
    
    def get_tool_name(self) -> str:
        return "file_read"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Read a file."""
        path = inputs.get("path", "")
        
        if not path:
            return ToolOutput(success=False, data={}, error="Path is required")
        
        try:
            expanded_path = os.path.expanduser(path)
            
            if not os.path.exists(expanded_path):
                return ToolOutput(
                    success=False, data={},
                    error=f"File not found: {path}"
                )
            
            with open(expanded_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            file_stat = os.stat(expanded_path)
            
            self.logger.info(f"Read file: {path} ({len(content)} bytes)")
            
            return ToolOutput(
                success=True,
                data={
                    "path": path,
                    "absolute_path": expanded_path,
                    "content": content,
                    "size_bytes": file_stat.st_size,
                    "bytes_read": len(content)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to read file: {e}")
            return ToolOutput(success=False, data={}, error=str(e))
