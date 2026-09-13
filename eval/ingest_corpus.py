#!/usr/bin/env python3
"""Ingest the pinned Haystack docs corpus into Open WebUI knowledge bases through the product API.
Creates (or reuses) knowledge bases named haystack-docs-<version>, uploads each .md/.mdx file (as text/markdown,
renamed to .md so the upstream loader treats it as text) and attaches it. Skips files already attached by name.
  .venv/bin/python eval/ingest_corpus.py --version 3.1 [--version 2.31] [--workers 4]
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("OPENWEBUI_URL", "http://127.0.0.1:8080")
CORPUS = os.path.join(ROOT, "corpus", "haystack-docs-src", "docs-website", "versioned_docs")


def api(path, token, data=None, method=None, multipart=None):
    req = urllib.request.Request(BASE + path, method=method or ("POST" if (data is not None or multipart) else "GET"))
    req.add_header("Authorization", f"Bearer {token}")
    body = None
    if multipart:
        boundary = uuid.uuid4().hex
        name, content, ctype = multipart
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    elif data is not None:
        req.add_header("Content-Type", "application/json"); body = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, body, timeout=600) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", action="append", required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    token = open(os.path.join(ROOT, "runtime", ".token")).read().strip()
    status, kbs = api("/api/v1/knowledge/", token)
    kbs = kbs.get("items", []) if isinstance(kbs, dict) else kbs
    by_name = {k["name"]: k for k in kbs}
    for ver in args.version:
        name = f"haystack-docs-{ver}"
        if name not in by_name:
            _, kb = api("/api/v1/knowledge/create", token, {"name": name, "description": f"Haystack docs version {ver} (Apache-2.0), pinned corpus"})
            by_name[name] = kb
        kb_id = by_name[name]["id"]
        _, kb_full = api(f"/api/v1/knowledge/{kb_id}", token)
        existing = {f.get("meta", {}).get("name") for f in (kb_full.get("files") or [])}
        vdir = os.path.join(CORPUS, f"version-{ver}")
        files = sorted(os.path.join(dp, fn) for dp, _, fns in os.walk(vdir) for fn in fns if fn.endswith((".md", ".mdx")))
        todo = []
        for f in files:
            rel = os.path.relpath(f, vdir)
            up_name = f"{ver}__" + rel.replace(os.sep, "__")
            up_name = up_name[:-4] + ".md" if up_name.endswith(".mdx") else up_name
            if up_name not in existing:
                todo.append((f, up_name))
        print(f"{name}: {len(files)} files, {len(existing)} already attached, {len(todo)} to ingest")
        t0 = time.time(); ok = fail = 0
        def one(item):
            f, up_name = item
            st, res = api("/api/v1/files/?process=true&process_in_background=false", token, multipart=(up_name, open(f, "rb").read(), "text/markdown"))
            if st != 200:
                return (up_name, f"upload {st}: {res}")
            st2, res2 = api(f"/api/v1/knowledge/{kb_id}/file/add", token, {"file_id": res["id"]})
            return (up_name, None if st2 == 200 else f"add {st2}: {res2}")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for up_name, err in ex.map(one, todo):
                if err: fail += 1; print("  FAIL", up_name, err[:160])
                else: ok += 1
        print(f"{name}: ingested {ok}, failed {fail}, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
