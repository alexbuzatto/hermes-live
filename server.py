#!/usr/bin/env python3
"""Painel ao vivo da orquestração do Hermes (somente leitura).

Le os arquivos de estado/delegação do Hermes e serve:
  /            -> painel animado (index.html)
  /api/state   -> estado atual (gateway, bots, lotes de delegação, eventos)
  /api/replay  -> todos os lotes encontrados, para replay
  /api/file?id=... -> log completo de uma task (texto)

Nao escreve nada em ~/.hermes.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERMES = Path(os.environ.get("HERMES_HOME", r"C:\Users\PAULA\AppData\Local\hermes"))
LIVE = HERMES / "cache" / "delegation" / "live"
PROFILES = HERMES / "profiles"
STATIC = Path(__file__).resolve().parent / "index.html"
PORT = int(os.environ.get("PAINEL_PORT", "8791"))

LINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+([a-z_]+)\s*\|\s?(.*)$")

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (now, value)
    return value


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return None


def gateway_state() -> dict:
    st = _read_json(HERMES / "gateway_state.json") or {}
    hb_age = None
    try:
        hb = json.loads((HERMES / "state" / "gateway.heartbeat").read_text(encoding="utf-8-sig"))
        ts = datetime.fromisoformat(hb["updated_at"])
        hb_age = round((datetime.now(timezone.utc) - ts).total_seconds(), 1)
    except Exception:
        pass
    return {
        "pid": st.get("pid"),
        "version": st.get("code_version"),
        "gateway_state": st.get("gateway_state"),
        "active_agents": st.get("active_agents", 0),
        "served_profiles": st.get("served_profiles", []),
        "heartbeat_age": hb_age,
        "alive": hb_age is not None and hb_age < 150,
        "updated_at": st.get("updated_at"),
    }


def _yaml_scalar(raw: str, key: str):
    m = re.search(rf"^{key}:\s*(.+)$", raw, re.MULTILINE)
    if not m:
        return ""
    val = m.group(1).strip().strip('"').strip("'")
    return val


def bots() -> list[dict]:
    out = []
    try:
        dirs = sorted(p for p in PROFILES.iterdir() if p.is_dir())
    except Exception:
        return out
    for d in dirs:
        if d.name == "default":
            continue  # o proprio Hermes, nao um especialista
        raw = ""
        try:
            raw = (d / "profile.yaml").read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            pass
        title = ""
        m = re.search(r"hermes-bots:\s*\n(?:.*\n)*?\s+title:\s*(.+)", raw)
        if m:
            title = m.group(1).strip().strip('"').strip("'")
        desc = _yaml_scalar(raw, "description")
        out.append({"name": d.name, "title": title or d.name.upper(), "description": desc})
    return out


def _parse_task_log(path: Path, limit: int = 40) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    lines = []
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        t, role, body = m.groups()
        body = body.strip()
        if not body:
            continue
        # remove sufixos de truncamento do próprio Hermes, tipo "…(+3399 chars)"
        body = re.sub(r"\s*â€¦\(\+\d+ chars\)$", "…", body)
        body = re.sub(r"\s*…\(\+\d+ chars\)$", "…", body)
        lines.append({"t": t, "role": role, "text": body[:4000], "short": len(body) > 4000})
    return lines[-limit:]


def batches(limit_lines: int = 40) -> list[dict]:
    def load():
        out = []
        if not LIVE.is_dir():
            return out
        for d in sorted(LIVE.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0):
            man = _read_json(d / "manifest.json")
            if not isinstance(man, dict):
                continue
            tasks = []
            for task in man.get("tasks") or []:
                idx = task.get("index", 0)
                logp = d / f"task-{idx}.log"
                tasks.append({
                    "index": idx,
                    "goal": task.get("goal", ""),
                    "status": task.get("status", "running"),
                    "exit_reason": task.get("exit_reason"),
                    "model": task.get("model"),
                    "lines": _parse_task_log(logp, limit_lines) if logp.exists() else [],
                })
            out.append({
                "id": man.get("delegation_id", d.name),
                "started": man.get("started"),
                "completed": man.get("completed"),
                "status": "completed" if man.get("completed") else "running",
                "model": man.get("model"),
                "provider": man.get("provider"),
                "task_count": man.get("task_count", len(tasks)),
                "tasks": tasks,
            })
        return out
    return _cached("batches", 1.0, load)


EVENT_PATTERNS = [
    (re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO gateway\.run: inbound message: .*?msg='([^']{0,200})"), "in"),
    (re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO gateway\.run: response ready: .*?time=([\d.]+)s api_calls=(\d+) response=(\d+) chars"), "out"),
    (re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO tools\.async_delegation: Dispatched async delegation batch (\w+)"), "dispatch"),
    (re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO .*Turn ended: reason=(\S+)"), "turn"),
]


def events(limit: int = 40) -> list[dict]:
    def load():
        path = HERMES / "logs" / "gateway.log"
        try:
            with path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 400_000))
                raw = fh.read().decode("utf-8", errors="replace")
        except Exception:
            return []
        out = []
        for line in raw.splitlines():
            for rx, kind in EVENT_PATTERNS:
                m = rx.match(line)
                if not m:
                    continue
                if kind == "in":
                    out.append({"at": m.group(1)[11:], "kind": "in", "text": m.group(2)[:160]})
                elif kind == "out":
                    out.append({"at": m.group(1)[11:], "kind": "out",
                                "text": f"resposta em {m.group(2)}s · {m.group(3)} chamadas · {m.group(4)} chars"})
                elif kind == "dispatch":
                    out.append({"at": m.group(1)[11:], "kind": "dispatch", "text": f"lote {m.group(2)} despachado"})
                else:
                    out.append({"at": m.group(1)[11:], "kind": "turn", "text": f"turno encerrado ({m.group(2)})"})
                break
        return out[-limit:]
    return _cached("events", 2.0, load)


def state() -> dict:
    bs = batches()
    running = [b for b in bs if b["status"] == "running"]
    return {
        "now": datetime.now().strftime("%H:%M:%S"),
        "gateway": gateway_state(),
        "bots": bots(),
        "batches": bs[-8:],
        "events": events(),
        "stats": {
            "total": len(bs),
            "running": len(running),
            "completed": sum(1 for b in bs if b["status"] == "completed"),
            "last": bs[-1]["started"] if bs else None,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesPainel/1.0"

    def log_message(self, fmt, *args):  # silencioso
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, payload, code: int = 200):
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            try:
                body = STATIC.read_bytes()
            except Exception:
                body = b"<h1>index.html nao encontrado</h1>"
                self._send(500, body, "text/html; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")
            return
        if url.path == "/api/state":
            try:
                self._json(state())
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if url.path == "/api/replay":
            try:
                self._json({"batches": batches(60), "bots": bots(), "events": events(120)})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if url.path == "/api/file":
            qs = parse_qs(url.query)
            bid = (qs.get("id") or [""])[0]
            idx = int((qs.get("task") or ["0"])[0])
            if not re.fullmatch(r"deleg_[0-9a-f]{8}", bid):
                self._json({"error": "id invalido"}, 400)
                return
            path = LIVE / bid / f"task-{idx}.log"
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                self._json({"error": "log nao encontrado"}, 404)
                return
            self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._json({"error": "not found"}, 404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"painel em http://127.0.0.1:{PORT}  (hermes_home={HERMES})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
