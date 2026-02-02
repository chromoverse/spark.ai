# app/tools/file_system/operations.py
"""
File System Operations Tools

Tools for file/folder creation, copying, etc.
These typically run on CLIENT but can run on server too
"""

import asyncio
import os
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from app.tools.base import BaseTool, ToolOutput


class CreateFileTool(BaseTool):
    """
    Create file tool
    
    Matches registry: file_create (though registry shows folder_create, we need both)
    
    Can run on: CLIENT (typically)
    """
    
    def get_tool_name(self) -> str:
        return "file_create"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Create a file with content
        
        Inputs:
            path: str - File path
            content: str - File content (default: "")
            overwrite: bool - Overwrite if exists (default: false)
        
        Returns:
            ToolOutput with file info
        """
        path = inputs.get("path", "")
        content = inputs.get("content", "")
        overwrite = inputs.get("overwrite", False)
        
        if not path:
            return ToolOutput(
                success=False,
                data={},
                error="Path is required"
            )
        
        try:
            # Expand user path
            expanded_path = os.path.expanduser(path)
            
            # Check if exists
            if os.path.exists(expanded_path) and not overwrite:
                return ToolOutput(
                    success=False,
                    data={},
                    error=f"File already exists: {path}"
                )
            
            # Create parent directories if needed
            parent_dir = os.path.dirname(expanded_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            # Write file
            with open(expanded_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Get file info
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
            return ToolOutput(
                success=False,
                data={},
                error=str(e)
            )


class FolderCreateTool(BaseTool):
    """
    Create folder tool
    
    Matches registry: folder_create
    
    Can run on: CLIENT (typically)
    """
    
    def get_tool_name(self) -> str:
        return "folder_create"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Create a folder/directory
        
        Inputs:
            path: str - Folder path
            recursive: bool - Create parent dirs (default: true)
        
        Returns:
            ToolOutput with folder info
        """
        path = inputs.get("path", "")
        recursive = inputs.get("recursive", True)
        
        if not path:
            return ToolOutput(
                success=False,
                data={},
                error="Path is required"
            )
        
        try:
            # Expand user path
            expanded_path = os.path.expanduser(path)
            
            # Create directory
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
            return ToolOutput(
                success=False,
                data={},
                error=str(e)
            )


class FileCopyTool(BaseTool):
    """
    Copy file tool
    
    Matches registry: file_copy
    
    Can run on: CLIENT (typically)
    """
    
    def get_tool_name(self) -> str:
        return "file_copy"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Copy a file
        
        Inputs:
            source: str - Source file path
            destination: str - Destination path
            overwrite: bool - Overwrite if exists (default: false)
        
        Returns:
            ToolOutput with copy info
        """
        source = inputs.get("source", "")
        destination = inputs.get("destination", "")
        overwrite = inputs.get("overwrite", False)
        
        if not source or not destination:
            return ToolOutput(
                success=False,
                data={},
                error="Both source and destination are required"
            )
        
        try:
            import shutil
            
            # Expand paths
            source_path = os.path.expanduser(source)
            dest_path = os.path.expanduser(destination)
            
            # Check source exists
            if not os.path.exists(source_path):
                return ToolOutput(
                    success=False,
                    data={},
                    error=f"Source file not found: {source}"
                )
            
            # Check destination
            if os.path.exists(dest_path) and not overwrite:
                return ToolOutput(
                    success=False,
                    data={},
                    error=f"Destination already exists: {destination}"
                )
            
            # Create destination directory if needed
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            
            # Copy file
            shutil.copy2(source_path, dest_path)
            
            # Get file info
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
            return ToolOutput(
                success=False,
                data={},
                error=str(e)
            )


class FileSearchTool(BaseTool):
    """
    File search tool
    
    Matches registry: file_search
    
    Can run on: CLIENT (typically)
    """
    
    def get_tool_name(self) -> str:
        return "file_search"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Search for files
        
        Inputs:
            query: str - Search query (filename pattern)
            path: str - Search path (default: ".")
            max_results: int - Max results (default: 50)
        
        Returns:
            ToolOutput with found files
        """
        query = inputs.get("query", "")
        search_path = inputs.get("path", ".")
        max_results = inputs.get("max_results", 50)
        
        if not query:
            return ToolOutput(
                success=False,
                data={},
                error="Query is required"
            )
        
        try:
            # Expand path
            expanded_path = os.path.expanduser(search_path)
            
            if not os.path.exists(expanded_path):
                return ToolOutput(
                    success=False,
                    data={},
                    error=f"Path not found: {search_path}"
                )
            
            self.logger.info(f"Searching for '{query}' in {search_path}")
            
            # Search files
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
            return ToolOutput(
                success=False,
                data={},
                error=str(e)
            )