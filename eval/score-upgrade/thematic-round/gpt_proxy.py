"""chat/completions → responses 协议翻译代理（key 仅驻内存，不入库不入日志）。"""
import json, re, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://cpr.flatkey.ai/v1/responses"
KEY = None  # 启动时注入

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.rstrip("/") == "/v1/models":
            self._json({"object": "list", "data": [
                {"id": "gpt-5.6-sol", "object": "model"},
                {"id": "gpt-5.6-terra", "object": "model"},
                {"id": "gpt-5.6-luna", "object": "model"}]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("content-length") or 0)
        req = json.loads(self.rfile.read(length))
        model = req.get("model") or "gpt-5.6-sol"
        messages = req.get("messages") or []
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        user_blocks = []
        for m in messages:
            if m.get("role") == "user":
                user_blocks.append(m.get("content"))
        up = {
            "model": model,
            "instructions": system or None,
            "input": user_blocks[-1] if user_blocks else "",
            "stream": True,
        }
        if req.get("max_tokens"):
            up["max_output_tokens"] = req["max_tokens"]
        body = json.dumps(up).encode()
        request = urllib.request.Request(UPSTREAM, data=body, method="POST", headers={
            "authorization": f"Bearer {KEY}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        })
        text, finish = [], "stop"
        try:
            with urllib.request.urlopen(request, timeout=300) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    etype = event.get("type")
                    if etype == "response.output_text.delta":
                        text.append(event.get("delta") or "")
                    elif etype == "response.completed":
                        resp_obj = event.get("response") or {}
                        details = resp_obj.get("status_details") or {}
                        if details.get("incomplete_details", {}).get("reason") == "max_output_tokens":
                            finish = "length"
                        if not text:
                            for out in resp_obj.get("output") or []:
                                for piece in out.get("content") or []:
                                    if piece.get("type") == "output_text":
                                        text.append(piece.get("text") or "")
        except Exception as error:  # noqa: BLE001
            self._json({"error": {"message": f"upstream: {error}"}}, 502)
            return
        full = "".join(text)
        self._json({
            "id": "proxy-chat", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": full}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def _json(self, obj, code=200):
        payload = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

if __name__ == "__main__":
    import sys
    KEY = open(sys.argv[2], encoding="utf-8").read().strip() if len(sys.argv) > 2 else None
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8907
    print(f"gpt proxy on :{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
