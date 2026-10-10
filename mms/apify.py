"""Minimal Apify REST client. The token is read from the APIFY_TOKEN env var at
runtime only and sent in the Authorization header (never in URLs, logs or files)."""
import os, time, requests

API = "https://api.apify.com/v2"


class ApifyError(Exception):
    pass


def _headers():
    tok = os.environ.get("APIFY_TOKEN", "").strip()
    if not tok:
        raise ApifyError("APIFY_TOKEN env var not set")
    return {"Authorization": f"Bearer {tok}"}


def check_token():
    """Return (ok, message). Never returns the token."""
    try:
        r = requests.get(f"{API}/users/me", headers=_headers(), timeout=30)
    except ApifyError as e:
        return False, str(e)
    except requests.RequestException as e:
        return False, f"network error: {type(e).__name__}"
    if r.status_code == 200:
        return True, "ok"
    try:
        err = r.json().get("error", {}).get("type", "")
    except Exception:
        err = ""
    return False, f"Apify rejected the token (HTTP {r.status_code} {err})".strip()


def run_actor(actor_id, run_input, timeout_s=900, max_items=None, max_charge_usd=None):
    """Start an actor run, wait for it, return (items, cost_usd)."""
    h = _headers()
    params = {}
    if max_items:
        params["maxItems"] = int(max_items)  # caps pay-per-result actors
    if max_charge_usd:
        params["maxTotalChargeUsd"] = f"{max_charge_usd:.2f}"  # hard spend cap for pay-per-event actors
    r = requests.post(f"{API}/acts/{actor_id}/runs", headers=h, json=run_input, params=params, timeout=60)
    if r.status_code >= 300:
        raise ApifyError(f"{actor_id}: start failed HTTP {r.status_code}: {r.text[:200]}")
    run = r.json()["data"]
    run_id = run["id"]
    t0 = time.time()
    while run["status"] in ("READY", "RUNNING"):
        if time.time() - t0 > timeout_s:
            requests.post(f"{API}/actor-runs/{run_id}/abort", headers=h, timeout=30)
            raise ApifyError(f"{actor_id}: timed out after {timeout_s}s (aborted)")
        time.sleep(5)
        run = requests.get(f"{API}/actor-runs/{run_id}", headers=h, timeout=30).json()["data"]
    time.sleep(3)  # usage/charges are finalised a moment after the run ends
    run = requests.get(f"{API}/actor-runs/{run_id}", headers=h, timeout=30).json()["data"]
    cost = float(run.get("usageTotalUsd") or 0.0)
    if run["status"] != "SUCCEEDED":
        raise ApifyError(f"{actor_id}: run {run['status']} (cost ${cost:.3f})")
    ds = run["defaultDatasetId"]
    items = requests.get(f"{API}/datasets/{ds}/items", headers=h,
                         params={"clean": "true", "format": "json"}, timeout=120).json()
    return items, cost
