"""
MCP Client Manager: Spawns stdio MCP server subprocesses, discovers tools,
and executes JSON-RPC 2.0 tool calls with latency tracking.
"""

import sys
import json
import time
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MCPToolInfo(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]
    server_id: str


class MCPClientManager:
    """Manager for genuine stdio MCP servers and client communication."""

    def __init__(self):
        self.server_configs: Dict[str, List[str]] = {}
        self.tools: Dict[str, MCPToolInfo] = {}

    def register_server(self, server_id: str, command: List[str]):
        """Register a server_id with its stdio execution command."""
        self.server_configs[server_id] = command

    def register_default_servers(self):
        """Register standard MCP tool servers."""
        python_exe = sys.executable
        base_path = Path(__file__).parent / "servers"
        
        self.register_server("repo_server", [python_exe, str(base_path / "repo_server.py")])
        self.register_server("github_server", [python_exe, str(base_path / "github_server.py")])
        self.register_server("web_search_server", [python_exe, str(base_path / "web_search_server.py")])

    def discover_tools(self) -> Dict[str, MCPToolInfo]:
        """
        Connects to all registered MCP servers via stdio,
        initializes protocol, and collects tool definitions dynamically.
        """
        self.tools.clear()
        if not self.server_configs:
            self.register_default_servers()

        for server_id, command in self.server_configs.items():
            try:
                proc = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                
                # 1. Send initialize
                init_req = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "InvestigatorAgent", "version": "1.0.0"}}
                }) + "\n"
                proc.stdin.write(init_req)
                proc.stdin.flush()
                init_resp_line = proc.stdout.readline()
                if not init_resp_line:
                    raise RuntimeError("MCP server did not respond to initialize")
                # Required MCP lifecycle notification: tools may only be used
                # after the initialization handshake has completed.
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                proc.stdin.flush()

                # 2. Send tools/list
                list_req = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list"
                }) + "\n"
                proc.stdin.write(list_req)
                proc.stdin.flush()
                list_resp_line = proc.stdout.readline()

                if list_resp_line:
                    resp_data = json.loads(list_resp_line)
                    tools_list = resp_data.get("result", {}).get("tools", [])
                    for tdata in tools_list:
                        tool_info = MCPToolInfo(
                            name=tdata["name"],
                            description=tdata["description"],
                            inputSchema=tdata.get("inputSchema", {}),
                            server_id=server_id
                        )
                        self.tools[tdata["name"]] = tool_info
                
                # Clean up discovery process
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception as e:
                logger.error(f"Failed to discover tools from MCP server '{server_id}': {str(e)}")
        
        return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        """
        Executes a dynamic MCP tool call on its corresponding stdio MCP server.
        Measures exact tool execution latency.
        """
        if tool_name not in self.tools:
            # Re-discover tools in case newly added
            self.discover_tools()

        if tool_name not in self.tools:
            return {
                "success": False,
                "tool_name": tool_name,
                "latency_sec": 0.0,
                "result": None,
                "error": f"Tool '{tool_name}' not registered in any MCP server."
            }

        tool_info = self.tools[tool_name]
        server_command = self.server_configs.get(tool_info.server_id)
        if not server_command:
            return {
                "success": False,
                "tool_name": tool_name,
                "latency_sec": 0.0,
                "result": None,
                "error": f"Server command for '{tool_info.server_id}' not found."
            }

        start_time = time.time()
        try:
            proc = subprocess.Popen(
                server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            # Perform the standard MCP handshake on every short-lived stdio
            # connection, then close stdin so communicate() can enforce the
            # configured timeout instead of blocking forever on readline().
            init_req = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "InvestigatorAgent", "version": "1.0.0"}}
            }) + "\n"
            initialized = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            call_req = json.dumps({
                "jsonrpc": "2.0",
                "id": 100,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }) + "\n"

            stdout, stderr = proc.communicate(input=init_req + initialized + call_req, timeout=timeout)
            latency = time.time() - start_time

            lines = [line for line in stdout.splitlines() if line.strip()]
            # The first line is initialize; the final response is tools/call.
            resp_line = lines[-1] if lines else ""

            if not resp_line:
                return {
                    "success": False,
                    "tool_name": tool_name,
                    "latency_sec": round(latency, 3),
                    "result": None,
                    "error": "No response output from MCP server stdio."
                }

            res_data = json.loads(resp_line)
            if "error" in res_data:
                return {
                    "success": False,
                    "tool_name": tool_name,
                    "latency_sec": round(latency, 3),
                    "result": None,
                    "error": res_data["error"].get("message", "MCP Tool Error")
                }

            content_list = res_data.get("result", {}).get("content", [])
            is_error = res_data.get("result", {}).get("isError", False)
            
            output_text = ""
            if content_list and len(content_list) > 0:
                output_text = content_list[0].get("text", "")
            
            # Try to parse JSON output if formatted
            try:
                parsed_payload = json.loads(output_text)
            except Exception:
                parsed_payload = output_text

            if is_error or (isinstance(parsed_payload, dict) and ("error" in parsed_payload or parsed_payload.get("status") == "FILE_NOT_FOUND")):
                err_msg = parsed_payload.get("error") if isinstance(parsed_payload, dict) else output_text
                return {
                    "success": False,
                    "tool_name": tool_name,
                    "latency_sec": round(latency, 3),
                    "result": None,
                    "error": str(err_msg) if err_msg else "Tool execution reported error"
                }

            return {
                "success": True,
                "tool_name": tool_name,
                "latency_sec": round(latency, 3),
                "result": parsed_payload,
                "error": None
            }

        except subprocess.TimeoutExpired:
            latency = time.time() - start_time
            proc.kill()
            proc.communicate()
            return {
                "success": False,
                "tool_name": tool_name,
                "latency_sec": round(latency, 3),
                "result": None,
                "error": f"Tool execution timed out after {timeout}s"
            }
        except Exception as e:
            latency = time.time() - start_time
            return {
                "success": False,
                "tool_name": tool_name,
                "latency_sec": round(latency, 3),
                "result": None,
                "error": f"MCP execution failure: {str(e)}"
            }

    def format_tools_for_prompt(self, compact: bool = True) -> str:
        """Formats discovered MCP tool schemas into system prompt string."""
        if not self.tools:
            self.discover_tools()

        lines = []
        for name, tinfo in self.tools.items():
            if compact:
                props = list(tinfo.inputSchema.get("properties", {}).keys())
                props_str = ", ".join(props)
                lines.append(f"- `{name}({props_str})`: {tinfo.description}")
            else:
                lines.append(f"- **{name}**: {tinfo.description}")
                lines.append(f"  Schema: `{json.dumps(tinfo.inputSchema)}`")
        return "\n".join(lines)
