#!/usr/bin/env python3
import argparse
import getpass
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from truenas_api_client import Client


## INIT ##

def dir_path(path: str) -> Path:
    p = Path(os.path.expanduser(path))
    if p.is_dir():
        return p
    raise argparse.ArgumentTypeError(f"'{path}' is not a valid directory")

parser = argparse.ArgumentParser(description="Bootstrap TrueNAS apps from docker compose files.")
parser.add_argument("--host", type=str, required=True, help="Hostname/IP of TrueNAS host")
parser.add_argument("--user", type=str, default="admin", help="Username to login with. DEFAULT: 'admin'")
parser.add_argument("--compose_dir", required=True, type=dir_path, help="Directory of compose files to deploy")
parser.add_argument("--dry-run", action="store_true", help="Show actions without making changes")
args = parser.parse_args()

ws_uri = f"ws://{args.host}/api/current"  # use wss:// in production


password = getpass.getpass("Please Enter your password: ")

class TNSession:
    def __init__(self, uri, user=None, password=None, api_key=None):
        self.uri = uri
        self.user = user
        self.password = password
        self.api_key = api_key
        self._c = None

    def open(self):
        """Open socket and authenticate once."""
        if self._c is not None:
            return
        self._c = Client(self.uri)
        self._c.__enter__()  # open ws
        if self.api_key:
            ok = self._c.call("auth.login_with_api_key", self.api_key)
        else:
            ok = self._c.call("auth.login", self.user, self.password)
        if not ok:
            self.close()
            raise SystemExit("Login failed")

    def close(self):
        if self._c is not None:
            try:
                self._c.__exit__(None, None, None)
            finally:
                self._c = None

    def call(self, method, *params, _retries=1, _backoff=1.0):
        """
        Reuse the same ws; auto-reconnect once if the socket drops or rate-limit hits.
        """
        self.open()
        for attempt in range(_retries + 1):
            try:
                return self._c.call(method, *params) if params else self._c.call(method)
            except Exception as e:
                msg = str(e).lower()
                # simple reconnect/backoff on common transient issues
                if "rate" in msg or "ratelimit" in msg or "broken pipe" in msg or "closed" in msg:
                    time.sleep(_backoff * (attempt + 1))
                    self.close()
                    self.open()
                    continue
                raise

    def ping(self):
        self.open()
        return getattr(self._c, "ping", lambda: self._c.call("ping"))()


# -------------------- API interactions --------------------

def validate_truenas():
    """Ensure Docker Application service is configured/running (for compose path)."""
    status = SESSION.call("docker.status")
    st = status.get("status")
    if st == "RUNNING":
        return
    if st == "UNCONFIGURED":
        raise SystemExit("Docker Application service is UNCONFIGURED. Configure it and try again.")
    raise SystemExit(f"Docker Application service is not healthy (status={st!r}).")

def watch_job(job_id: int, poll=1.0, raw_result=True):
    last_percent = None
    last_desc = None
    last_excerpt = None

    while True:
        job = SESSION.call(
            "core.get_jobs",
            [["id", "=", job_id]],
            {"get": True, "extra": {"raw_result": raw_result}}
        )

        state = job.get("state")
        prog  = (job.get("progress") or {})
        pct   = prog.get("percent")
        desc  = prog.get("description")
        logs  = job.get("logs_excerpt")
        #res   = job.get("result")
        err   = job.get("error") or job.get("result_encoding_error")

        # Print changes only
        if pct != last_percent or desc != last_desc:
            print(f"[job {job_id}] {state} {pct if pct is not None else ''}% {('- ' + desc) if desc else ''}")
            last_percent, last_desc = pct, desc

        if logs and logs != last_excerpt:
            print(f"[job {job_id} logs]\n{logs}")
            last_excerpt = logs

        if state in ("SUCCESS", "FAILED", "ABORTED"):
            if state == "SUCCESS":
                print(f"[job {job_id}] Finished.")
            else:
                print(f"[job {job_id}] {state}. error = {err!r}")
            return job

        time.sleep(poll)

def update_app(app_name: str, compose: bool, desired_spec: Dict[str, Any]):
    desired_spec = (
        {"custom_compose_config": desired_spec}
        if compose
        else {"values": {}}
    )

    job_id = SESSION.call("app.update", app_name, desired_spec)
    watch_job(job_id)

def deploy_app(file_path: Path, is_compose: bool):
    app_name = file_path.stem
    desired_config = validate_and_normalize(file_path)
    app_exists = SESSION.call("app.query", [["name", "=", app_name]], {"limit": 1})

    if app_exists:
        current_config = SESSION.call("app.config", app_name)
        needs_update = not json_equivalent(desired_config, current_config)
        if needs_update: 
            print(f"[UPDATE] {app_name} -- Config has drifted. Updating....")
            update_app(app_name, is_compose, desired_config)
        else:
            print(f"[SKIP] {app_name} -- App Exists, and the config is up to date.")
    elif not app_exists:

        if is_compose:
            payload = { 
                "app_name": app_name, 
                "custom_app": True, 
                "custom_compose_config": desired_config
                }
            print(f"[CREATE] {app_name} -- App is defined, but not deployed. Deploying...")
            job_id = SESSION.call("app.create", payload, )
            watch_job(job_id)
        else:
            print(f"[CREATE] {app_name} -- App Catalog is defined, but not deployed. Deploying...")
            payload = desired_config
            job_id = SESSION.call("app.create", payload, )
            watch_job(job_id)



def extract_current_spec(app_obj: Dict[str, Any], compose: bool) -> Dict[str, Any]:
    if compose:
        cfg = get_app_config(app_obj)  # expected: {"services": {...}, ...}
        if "services" in cfg and isinstance(cfg["services"], dict):
            return {"custom_app": True, "custom_compose_config": cfg}
        return {}
    # Chart/catalog (best-effort; adjust to your env if needed)
    for k in ("values", "config", "chart_values"):
        v = app_obj.get(k)
        if isinstance(v, dict):
            return {"values": v}
    return {}


# -------------------- helpers --------------------


def validate_and_normalize(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()
    try:
        if ext in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif ext == ".json":
            data = json.loads(text)
        else:
            raise ValueError(f"{path} must be .yaml, .yml, or .json")
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ValueError(f"{path.name} is not valid {ext.lstrip('.')}: {e}")

    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a top-level object/dict")
    return data



def canonicalize(obj: Any) -> Any:
    """Stable deep-compare: sort dict keys and lists where possible."""
    if isinstance(obj, dict):
        return {k: canonicalize(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        try:
            return [canonicalize(x) for x in sorted(obj, key=lambda v: json.dumps(v, sort_keys=True))]
        except Exception:
            return [canonicalize(x) for x in obj]
    return obj


def json_equivalent(a: Any, b: Any) -> bool:
    return canonicalize(a) == canonicalize(b)




# -------------------- main --------------------

## TODO need to integrate api_key into the args and use the right method based on the flags passed to the program
# If using an API key instead:
# SESSION = TNSession(ws_uri, api_key="TNAPI-...")

# Open the TrueNAS WebSocket session
SESSION = TNSession(ws_uri, user=args.user, password=password)
SESSION.open()

# Check docker status
validate_truenas()


if args.compose_dir:
    for file in sorted(args.compose_dir.iterdir()):
        if file.is_file():
            deploy_app(file, is_compose=True)
