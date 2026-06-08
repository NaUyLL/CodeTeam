#!/usr/bin/env python3
"""HTTP Gateway — 通过 HTTP/SSE 暴露 Room 接口。"""
from __future__ import annotations
import json, threading, time
from collections.abc import Callable
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import BaseGateway


# ── SSE 帮助类 ──

class SSEMessage:
    """Server-Sent Events 数据块"""
    def __init__(self, data: str, event: str = "message"):
        self.data = data
        self.event = event

    def encode(self) -> bytes:
        lines = self.data.split("\n")
        s = f"event: {self.event}\n" + "\n".join(f"data: {l}" for l in lines) + "\n\n"
        return s.encode("utf-8")


# ── HTTP Handler ──

class _Handler(BaseHTTPRequestHandler):
    """处理 HTTP 请求，通过 gateway 引用访问 Room"""

    gateway: "HTTPGateway" = None  # type: ignore  # 由 HTTPGateway 在创建时注入

    # ── 基础 ──

    def _json(self, data, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _html(self, content: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _text(self, content: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _error(self, msg: str, status: int = 400):
        self._json({"error": msg}, status=status)

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length).decode("utf-8") if length > 0 else ""

    def _cors(self):
        if self.command == "OPTIONS":
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    # ── API 路由 ──

    def do_OPTIONS(self):
        self._cors()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/":
            self._html(INDEX_HTML)
        elif path == "/api/members":
            self._json(self.gateway.list_members())
        elif path == "/api/history":
            tail = int(params.get("tail", [20])[0])
            self._json(self.gateway.get_history(tail=tail))
        elif path == "/api/status":
            self._json({
                "name": self.gateway.room.name,
                "members": len(self.gateway.room.members),
                "messages": len(self.gateway.room.history),
            })
        else:
            self._error("Not Found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        body = self._read_body()
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._error("Invalid JSON")
            return

        if path == "/chat":
            message = data.get("message", "").strip()
            if not message:
                self._error("message is required")
                return
            responses = self.gateway.handle_message("user", message)
            self._json(responses)
        elif path == "/save":
            path = data.get("path", "session.json")
            try:
                result = self.gateway.save_session(path)
                self._json({"saved": True, "path": path, "size_kb": len(result) / 1024})
            except Exception as e:
                self._error(str(e))
        else:
            self._error("Not Found", 404)

    def log_message(self, fmt, *args):
        pass  # 安静模式


# ── HTTPGateway ──

class HTTPGateway(BaseGateway):
    """HTTP 传输层 (ThreadingHTTPServer)"""

    def __init__(self, room, host: str = "0.0.0.0", port: int = 8765, name: str = "http"):
        super().__init__(room, name)
        self.host = host
        self.port = port
        _Handler.gateway = self

    def run(self):
        server = HTTPServer((self.host, self.port), _Handler)
        print(f"🚀 HTTP Gateway 启动: http://{self.host}:{self.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()

    def stop(self):
        pass


# ── HTML UI ── (保持与之前相同的 UI)

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>CodeTeam Room</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f5f5f5; height: 100vh; display: flex; }
.sidebar { width: 240px; background: #fff; border-right: 1px solid #e0e0e0; padding: 16px; overflow-y: auto; }
.sidebar h2 { font-size: 14px; color: #666; margin-bottom: 8px; }
.member { padding: 8px; margin: 4px 0; border-radius: 8px; font-size: 14px; color: #333; background: #f0f0f0; }
.main { flex: 1; display: flex; flex-direction: column; }
.header { padding: 16px 20px; border-bottom: 1px solid #e0e0e0; background: #fff; }
.header h1 { font-size: 18px; color: #333; }
.messages { flex: 1; padding: 16px 20px; overflow-y: auto; }
.msg { margin-bottom: 12px; padding: 12px; border-radius: 8px; max-width: 80%; }
.msg.user { background: #e3f2fd; margin-right: auto; }
.msg.agent { background: #fff; border: 1px solid #e0e0e0; margin-left: auto; }
.msg .sender { font-size: 12px; color: #888; margin-bottom: 4px; }
.msg .content { font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.msg.dm { background: #f3e5f5; }
.input-area { padding: 16px 20px; border-top: 1px solid #e0e0e0; background: #fff; display: flex; gap: 8px; }
.input-area input { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
.input-area input:focus { outline: none; border-color: #1976d2; }
.input-area button { padding: 10px 20px; background: #1976d2; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.input-area button:hover { background: #1565c0; }
.typing { font-size: 13px; color: #999; margin: 8px 20px; font-style: italic; }
</style>
</head>
<body>
<div class="sidebar">
  <h2>👥 成员</h2>
  <div id="member-list"><div class="member">加载中...</div></div>
</div>
<div class="main">
  <div class="header"><h1>🏠 CodeTeam Room</h1></div>
  <div class="messages" id="messages"></div>
  <div id="typing" class="typing" style="display:none;">Agent 思考中...</div>
  <div class="input-area">
    <input id="input" type="text" placeholder="输入消息，按 Enter 发送..." autofocus>
    <button onclick="send()">发送</button>
  </div>
</div>
<script>
async function loadMembers() {
  const res = await fetch('/api/members');
  const data = await res.json();
  document.getElementById('member-list').innerHTML =
    data.map(m => `<div class="member">🤖 ${m.name}</div>`).join('');
}

async function send() {
  const input = document.getElementById('input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addMessage('user', msg, 'user');
  const typing = document.getElementById('typing');
  typing.style.display = 'block';
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    const replies = await res.json();
    replies.forEach(r => addMessage(r.sender, r.content, 'agent'));
  } catch (e) {
    addMessage('system', `Error: ${e.message}`, 'agent');
  }
  typing.style.display = 'none';
}

function addMessage(sender, content, cls) {
  const div = document.createElement('div');
  div.className = `msg ${cls}`;
  div.innerHTML = `<div class="sender">${sender}</div><div class="content">${escapeHtml(content)}</div>`;
  document.getElementById('messages').appendChild(div);
  div.scrollIntoView({behavior: 'smooth'});
}

function escapeHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('input').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
loadMembers();
</script>
</body>
</html>"""
