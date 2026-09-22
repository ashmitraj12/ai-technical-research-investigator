"""
Model Context Protocol (MCP) JSON-RPC 2.0 Stdio Protocol Utilities.
"""

import json
import sys
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class MCPToolSchema(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class MCPServerBase:
    """Base class for stdio-based MCP servers."""

    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, description: str, input_schema: Dict[str, Any], handler):
        """Register a tool with its JSON schema and execution handler."""
        self.tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler
        }

    def run_stdio(self):
        """Main stdio loop reading JSON-RPC lines from stdin and writing to stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                req_id = request.get("id")
                method = request.get("method")
                params = request.get("params", {})

                # JSON-RPC notifications deliberately do not receive a
                # response.  In particular this is the MCP initialization
                # completion notification required before tools/list/call.
                if method == "notifications/initialized":
                    continue

                if method == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": self.name, "version": self.version}
                        }
                    }
                elif method == "tools/list":
                    tool_list = []
                    for tname, tinfo in self.tools.items():
                        tool_list.append({
                            "name": tinfo["name"],
                            "description": tinfo["description"],
                            "inputSchema": tinfo["inputSchema"]
                        })
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"tools": tool_list}
                    }
                elif method == "tools/call":
                    tool_name = params.get("name")
                    arguments = params.get("arguments", {})
                    if tool_name not in self.tools:
                        response = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32601, "message": f"Tool '{tool_name}' not found on server {self.name}"}
                        }
                    else:
                        try:
                            handler = self.tools[tool_name]["handler"]
                            res_content = handler(**arguments)
                            
                            is_err = False
                            if isinstance(res_content, dict):
                                if "error" in res_content or res_content.get("status") in [
                                    "FILE_NOT_FOUND", "NOT_A_DIRECTORY", "MISSING_ARGUMENT", "ERROR", "INVALID_ACTION"
                                ]:
                                    is_err = True

                            response = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": json.dumps(res_content) if isinstance(res_content, (dict, list)) else str(res_content)
                                        }
                                    ],
                                    "isError": is_err
                                }
                            }
                        except Exception as e:
                            response = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "content": [
                                        {"type": "text", "text": f"Tool execution error: {str(e)}"}
                                    ],
                                    "isError": True
                                }
                            }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Method '{method}' not supported"}
                    }

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
