#!/usr/bin/env python3
"""Exercise the browser chat path with a REAL socket session (what the UI does), not the bare API.
Connects a socket.io client, joins as the user, creates a chat, then sends the same knowledge-attached question with
function_calling=native and =legacy, capturing socket chat-events (tool calls, status, sources) and the final answer.
  .venv/bin/python eval/session_chat_test.py --kb <knowledge id> --qid q01 [--modes native,legacy]
Output: runtime/eval/session/<qid>-<mode>.json. Nothing here generates ground truth; a person judges the answers.
"""
import argparse, json, os, re, sys, threading, time, urllib.request, uuid
import socketio, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("OPENWEBUI_URL", "http://127.0.0.1:8080")


def api(path, token, data=None, method=None):
    req = urllib.request.Request(BASE + path, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Authorization", f"Bearer {token}")
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json"); body = json.dumps(data).encode()
    with urllib.request.urlopen(req, body, timeout=900) as r:
        return json.loads(r.read().decode() or "null")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True); ap.add_argument("--qid", default="q01")
    ap.add_argument("--modes", default="native,legacy"); ap.add_argument("--model", default="qwen3-4b")
    ap.add_argument("--no-files", action="store_true", help="do not attach the knowledge base to the request (use model knowledge instead)")
    args = ap.parse_args()
    token = open(os.path.join(ROOT, "runtime", ".token")).read().strip()
    q = next(x for x in yaml.safe_load(open(os.path.join(ROOT, "eval", "questions.yaml"))) if x["id"] == args.qid)
    kb = api(f"/api/v1/knowledge/{args.kb}", token)
    events, lock = [], threading.Lock()
    sio = socketio.Client(logger=False, engineio_logger=False)

    @sio.on("chat-events")
    def on_chat_events(data):
        with lock:
            events.append({"t": time.time(), "event": data})

    sio.connect(BASE, socketio_path="/ws/socket.io", auth={"token": token}, transports=["websocket"])
    sio.emit("user-join", {"auth": {"token": token}})
    time.sleep(1.0)
    sid = sio.get_sid()
    os.makedirs(os.path.join(ROOT, "runtime", "eval", "session"), exist_ok=True)
    for mode in args.modes.split(","):
        with lock:
            events.clear()
        chat = api("/api/v1/chats/new", token, {"chat": {"title": f"session-test {args.qid} {mode}", "models": [args.model], "messages": [], "history": {"messages": {}, "currentId": None}}})
        chat_id = chat["id"]; msg_id = str(uuid.uuid4())
        body = {"model": args.model, "stream": False, "messages": [{"role": "user", "content": q["question"] + " Answer briefly with citations. /no_think"}],
                "files": None if args.no_files else [{"type": "collection", "id": kb["id"], "name": kb["name"], "status": "processed"}],
                "params": {"function_calling": mode}, "features": {"web_search": False, "image_generation": False, "code_interpreter": False},
                "session_id": sid, "chat_id": chat_id, "id": msg_id, "background_tasks": {"title_generation": False, "tags_generation": False, "follow_up_generation": False}}
        t0 = time.time()
        try:
            res = api("/api/chat/completions", token, body)
            http_error = None
        except Exception as e:
            res = {"error": str(e)}; http_error = str(e)
        dt = time.time() - t0
        raw = json.dumps(res)[:300] if isinstance(res, dict) else str(res)[:300]
        # With session_id + chat_id the server processes in the background and persists the assistant message into the chat.
        deadline = time.time() + 900; saved = None
        while http_error is None and time.time() < deadline:
            ch = api(f"/api/v1/chats/{chat_id}", token)
            msgs = ((ch.get("chat") or {}).get("history") or {}).get("messages") or {}
            for mm in msgs.values():
                if mm.get("role") == "assistant" and mm.get("done"):
                    saved = mm
            if saved:
                break
            time.sleep(3)
        dt = time.time() - t0
        done_payload = {"done": True, "content": saved.get("content", ""), "usage": saved.get("usage"), "sources": saved.get("sources"),
                        "statusHistory": saved.get("statusHistory")} if saved else None
        with lock:
            evs = list(events)
        if done_payload:
            res = {"choices": [{"message": {"content": done_payload.get("content", "")}}], "usage": done_payload.get("usage"), "sources": done_payload.get("sources"), "raw_http": raw, "statusHistory": done_payload.get("statusHistory")}
        else:
            res = {"raw_http": raw, "error": http_error or "no persisted assistant message within timeout"}
        types = []
        tool_names = []
        for e in evs:
            d = (e["event"] or {}).get("data") or {}
            types.append(d.get("type"))
            payload = d.get("data") or {}
            if isinstance(payload, dict):
                for tc in (payload.get("tool_calls") or []):
                    tool_names.append(((tc.get("function") or {}).get("name")) or tc.get("name"))
                if d.get("type") == "chat:message:delta" or d.get("type") == "chat:completion":
                    ch = (payload.get("choices") or [{}])[0] if isinstance(payload.get("choices"), list) else {}
                    for tc in ((ch.get("message") or {}).get("tool_calls") or []) + ((ch.get("delta") or {}).get("tool_calls") or []):
                        tool_names.append(((tc.get("function") or {}).get("name")))
        msg = (res.get("choices") or [{}])[0].get("message", {}) if isinstance(res, dict) else {}
        text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
        srcs = res.get("sources") if isinstance(res, dict) else None
        out = {"qid": args.qid, "mode": mode, "chat_id": chat_id, "session_id": sid, "wall_s": round(dt, 1), "answer": text,
               "usage": res.get("usage") if isinstance(res, dict) else None, "sources": [[m.get("name") for m in s.get("metadata", [])] for s in (srcs or [])],
               "n_events": len(evs), "event_types": sorted({t for t in types if t}), "tool_calls_seen": [t for t in tool_names if t],
               "error": res.get("error") if isinstance(res, dict) else None, "raw_http": res.get("raw_http"), "statusHistory": [(x.get("action"), (x.get("description") or "")[:120]) for x in (res.get("statusHistory") or [])] if isinstance(res, dict) else None}
        json.dump({"result": out, "events": evs[:200]}, open(os.path.join(ROOT, "runtime", "eval", "session", f"{args.qid}-{mode}.json"), "w"), indent=2, default=str)
        print(json.dumps(out, ensure_ascii=False)[:1500])
    sio.disconnect()


if __name__ == "__main__":
    sys.exit(main())
