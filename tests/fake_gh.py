"""Closed-PATH gh oracle: local state and bare Git only; canonical CASE is literal."""

import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote

args = sys.argv[1:]
method, endpoint = args[args.index("--method") + 1:args.index("--method") + 3]
payload = json.load(sys.stdin) if "--input" in args and args[args.index("--input") + 1] == "-" else None
with open(os.environ["GH_LOG"], "a") as out:
    out.write(json.dumps({"method": method, "endpoint": endpoint, "payload": payload}) + "\n")
state_path = Path(os.environ["GH_STATE"])
state = json.loads(state_path.read_text())
base = "repos/miyako/4d-plugin-CLD2"
upload = "https://uploads.github.com/repos/miyako/4d-plugin-CLD2/releases/789/assets"
if endpoint == "user" or endpoint.startswith("user/"):
    sys.exit("HTTP 403 Resource not accessible by integration: installation token has no user endpoint")
if not (endpoint == base or endpoint.startswith(base + "/")
        or endpoint.startswith(upload + "?name=")):
    sys.exit("WRONG CANONICAL CLD2 REPOSITORY: " + endpoint)
mode = os.environ.get("GH_MODE", "")
stage = ""
if method == "GET" and endpoint == base:
    stage, result = "identity", {"id": 456, "full_name": "miyako/4d-plugin-CLD2"}
    if mode in ("identity-401", "identity-403"):
        sys.exit("HTTP " + mode.rsplit("-", 1)[1] + " installation authentication denied")
elif method == "GET" and "/releases?" in endpoint:
    page = int(endpoint.rsplit("page=", 1)[1])
    stage = "page" + str(page)
    if mode == "later-error" and page == 2:
        sys.exit("HTTP 404")
    pages = state.get("pages", [[]])
    result = pages[page - 1] if page <= len(pages) else []
elif method == "GET" and "/matching-refs/" in endpoint:
    stage, result = "refs", state.get("refs", [])
elif method == "GET" and "/git/ref/tags/" in endpoint:
    stage = "exact" if "--include" in args else "verify"
    if "--include" in args and not state.get("tag"):
        if mode == "exact-network":
            sys.exit("network failed")
        if mode == "exact-auth":
            print('HTTP/2.0 403 Forbidden\n\n{"message":"Forbidden"}')
            sys.exit(1)
        if mode == "exact-malformed404":
            print('HTTP/2.0 404 Not Found\n\n{"message":"other"}')
            sys.exit(1)
        print('HTTP/2.0 404 Not Found\nContent-Type: application/json\n\n'
              '{"message":"Not Found","status":"404"}')
        sys.exit(1)
    if mode == "verify-error":
        sys.exit("HTTP 403")
    result = {"ref": state.get("tag_name", "refs/tags/" + endpoint.rsplit("/", 1)[1]),
              "object": {"sha": state.get("tag"), "type": "commit"}}
    if mode == "bad-verify":
        result["object"]["type"] = "tag"
    if "--include" in args:
        print("HTTP/2.0 200 OK\nContent-Type: application/json\n")
elif method == "POST" and endpoint == base + "/git/refs":
    stage = "tag"
    state["tag"] = "b" * 40 if mode == "different-tag-race" else payload["sha"]
    state["tag_name"] = payload["ref"]
    state_path.write_text(json.dumps(state))
    subprocess.run(["git", "--git-dir=" + os.environ["GH_BARE_ORIGIN"], "update-ref",
                    payload["ref"], state["tag"]], check=(mode != "different-tag-race"),
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if mode in ("same-tag-race", "different-tag-race", "tag-error"):
        sys.exit("HTTP 422 occupied/response lost")
    result = {"ref": payload["ref"], "object": {"sha": payload["sha"], "type": "commit"}}
    if mode == "bad-tag":
        result["object"]["sha"] = "b" * 40
elif method == "POST" and endpoint == base + "/releases":
    stage = "release"
    state["release"] = payload
    state_path.write_text(json.dumps(state))
    if mode == "release-error":
        sys.exit("HTTP 422 response lost")
    result = dict(payload, id=789, upload_url=upload + "{?name,label}")
    if mode == "reused-id":
        result["id"] = 1
elif method == "POST" and endpoint.startswith(upload + "?name="):
    stage = "upload"
    path = Path(args[args.index("--input") + 1])
    assert unquote(endpoint.split("?name=", 1)[1]) == path.name
    state.setdefault("uploaded", []).append(path.name)
    state_path.write_text(json.dumps(state))
    if mode == "upload-" + path.suffix[1:]:
        sys.exit("HTTP 500 response lost")
    result = {"id": 45, "name": path.name, "size": path.stat().st_size, "state": "uploaded"}
else:
    sys.exit("UNSTUBBED/MUTATING API OPERATION: " + str(args))
if os.environ.get("GH_OVERRIDE_STAGE") == stage:
    if os.environ.get("GH_OVERRIDE_EXIT"):
        sys.exit("fixture transport failure")
    if os.environ.get("GH_RAW_JSON"):
        print(os.environ["GH_RAW_JSON"])
        sys.exit(0)
    result = json.loads(os.environ["GH_OVERRIDE_JSON"])
print(json.dumps(result))
