#!/usr/bin/env python3
# /// script
# dependencies = ["mcp>=1.0.0"]
# ///
"""
Interactive Document Editor MCP Server

Provides two tools:
1. collect_comments - Render markdown in a web UI for paragraph-level comment collection
2. review_changes - Show original vs suggested diffs for Accept/Reject decisions
"""

import asyncio
import json
import os
import signal
import socket
import sys
import tempfile
import threading
import uuid
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from web_ui import parse_markdown_paragraphs, generate_comment_html, generate_review_html


# Global state for the HTTP server
_result: dict | None = None
_result_event = threading.Event()


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        return s.getsockname()[1]


class EditorHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler for serving the editor UI and receiving results."""

    def __init__(self, *args, serve_dir: str, **kwargs):
        self.serve_dir = serve_dir
        super().__init__(*args, directory=serve_dir, **kwargs)

    def do_POST(self):
        """Handle POST request for submitting results."""
        global _result

        if self.path == '/submit':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                _result = json.loads(post_data.decode('utf-8'))
                _result_event.set()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """Suppress logging to stderr."""
        pass


def make_handler(serve_dir: str):
    """Factory to create handler with serve_dir bound."""
    def handler(*args, **kwargs):
        return EditorHTTPHandler(*args, serve_dir=serve_dir, **kwargs)
    return handler


async def _serve_and_wait(html_content: str, timeout: int = 7200) -> dict[str, Any]:
    """
    Common pattern: write HTML to temp dir, serve via HTTP, open browser, wait for submit.
    Returns the submitted result or error/timeout dict.
    """
    global _result, _result_event

    # Reset state
    _result = None
    _result_event.clear()

    # Create temp directory
    session_id = str(uuid.uuid4())[:8]
    serve_dir = Path(tempfile.gettempdir()) / f"claude-doc-editor-{session_id}"
    serve_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Find a free port
        port = find_free_port()

        # Write HTML
        html_path = serve_dir / "index.html"
        html_path.write_text(html_content, encoding='utf-8')

        # Start HTTP server in a thread
        server = HTTPServer(('localhost', port), make_handler(str(serve_dir)))
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        # Open browser
        url = f"http://localhost:{port}/index.html"
        webbrowser.open(url)

        # Wait for result
        result_received = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _result_event.wait(timeout)
        )

        # Shutdown server
        server.shutdown()

        if not result_received:
            return {
                "status": "timeout",
                "message": f"Timed out after {timeout // 60} minutes"
            }

        if _result is None:
            return {
                "status": "error",
                "message": "No result received"
            }

        return _result

    finally:
        try:
            import shutil
            shutil.rmtree(serve_dir, ignore_errors=True)
        except Exception:
            pass


async def collect_comments_impl(content: str, title: str = "Document") -> dict[str, Any]:
    """
    Phase 1: Render markdown in web UI for paragraph-level comment collection.

    Args:
        content: Markdown content string
        title: Document title

    Returns:
        Dict with status and comments list
    """
    paragraphs = parse_markdown_paragraphs(content)

    if not paragraphs:
        return {
            "status": "error",
            "message": "No paragraphs found in the content"
        }

    # We need a port for the HTML, but _serve_and_wait finds it internally.
    # So we generate HTML with a placeholder and replace, or we refactor.
    # Let's refactor: generate HTML needs port, so we do it inline.

    global _result, _result_event
    _result = None
    _result_event.clear()

    session_id = str(uuid.uuid4())[:8]
    serve_dir = Path(tempfile.gettempdir()) / f"claude-doc-editor-{session_id}"
    serve_dir.mkdir(parents=True, exist_ok=True)

    try:
        port = find_free_port()
        html_content = generate_comment_html(title, content, paragraphs, port)

        html_path = serve_dir / "index.html"
        html_path.write_text(html_content, encoding='utf-8')

        server = HTTPServer(('localhost', port), make_handler(str(serve_dir)))
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        url = f"http://localhost:{port}/index.html"
        webbrowser.open(url)

        timeout = 7200
        result_received = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _result_event.wait(timeout)
        )

        server.shutdown()

        if not result_received:
            return {"status": "timeout", "message": "Timed out after 2 hours"}

        if _result is None:
            return {"status": "error", "message": "No result received"}

        return _result

    finally:
        try:
            import shutil
            shutil.rmtree(serve_dir, ignore_errors=True)
        except Exception:
            pass


async def review_changes_impl(changes: list[dict]) -> dict[str, Any]:
    """
    Phase 2: Show original vs suggested diffs for Accept/Reject decisions.

    Args:
        changes: List of dicts with keys: paragraph_index, original, suggested, instruction

    Returns:
        Dict with status and decisions list
    """
    if not changes:
        return {
            "status": "error",
            "message": "No changes provided"
        }

    global _result, _result_event
    _result = None
    _result_event.clear()

    session_id = str(uuid.uuid4())[:8]
    serve_dir = Path(tempfile.gettempdir()) / f"claude-doc-editor-{session_id}"
    serve_dir.mkdir(parents=True, exist_ok=True)

    try:
        port = find_free_port()
        html_content = generate_review_html("Review Changes", changes, port)

        html_path = serve_dir / "index.html"
        html_path.write_text(html_content, encoding='utf-8')

        server = HTTPServer(('localhost', port), make_handler(str(serve_dir)))
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        url = f"http://localhost:{port}/index.html"
        webbrowser.open(url)

        timeout = 7200
        result_received = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _result_event.wait(timeout)
        )

        server.shutdown()

        if not result_received:
            return {"status": "timeout", "message": "Timed out after 2 hours"}

        if _result is None:
            return {"status": "error", "message": "No result received"}

        return _result

    finally:
        try:
            import shutil
            shutil.rmtree(serve_dir, ignore_errors=True)
        except Exception:
            pass


# Create MCP server
app = Server("interactive-document-editor")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="collect_comments",
            description="""Open an interactive web UI to collect paragraph-level editing instructions on a markdown document.

The user can:
- Click on any paragraph to select it
- Enter editing instructions (e.g., "make this more concise", "change tone to formal")
- Submit all comments at once

Returns a list of comments with paragraph index, original text, and user instruction.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Markdown content to display for commenting"
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title",
                        "default": "Document"
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="review_changes",
            description="""Open an interactive web UI to review proposed changes (original vs suggested) with Accept/Reject for each.

The user can:
- See a diff view of each proposed change (original in red, suggested in green)
- Accept or Reject each change individually
- Accept All or Reject All at once
- Submit final decisions

Returns a list of decisions with accepted/rejected status for each change.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array",
                        "description": "List of proposed changes to review",
                        "items": {
                            "type": "object",
                            "properties": {
                                "paragraph_index": {
                                    "type": "integer",
                                    "description": "Index of the paragraph in the document"
                                },
                                "original": {
                                    "type": "string",
                                    "description": "Original paragraph text"
                                },
                                "suggested": {
                                    "type": "string",
                                    "description": "AI-suggested replacement text"
                                },
                                "instruction": {
                                    "type": "string",
                                    "description": "The user's original editing instruction"
                                }
                            },
                            "required": ["paragraph_index", "original", "suggested", "instruction"]
                        }
                    }
                },
                "required": ["changes"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "collect_comments":
        content = arguments.get("content", "")
        title = arguments.get("title", "Document")
        result = await collect_comments_impl(content, title)
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )]

    elif name == "review_changes":
        changes = arguments.get("changes", [])
        result = await review_changes_impl(changes)
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )]

    return [TextContent(
        type="text",
        text=json.dumps({"error": f"Unknown tool: {name}"})
    )]


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    def handle_shutdown(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGHUP, handle_shutdown)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


async def main():
    """Main entry point."""
    setup_signal_handlers()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    except (BrokenPipeError, ConnectionResetError, EOFError):
        pass
    except KeyboardInterrupt:
        pass
    finally:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
