import asyncio
import json
import logging
import os
import re
import socket
import urllib.parse
from typing import Optional

import httpx

try:
    import websockets
except ImportError:
    websockets = None

logger = logging.getLogger(__name__)


def resolve_cdp_host() -> str:
    """
    Resolves the CDP host IP/domain.
    Docker on Mac resolves host.docker.internal to an IP (e.g. 0.250.250.254 or 192.168.65.2).
    Direct IP connects to Chrome without Host header rejection.
    """
    env_url = os.getenv("CDP_URL")
    if env_url:
        return env_url.rstrip("/")

    # Check host.docker.internal
    try:
        ip = socket.gethostbyname("host.docker.internal")
        return f"http://{ip}:9222"
    except Exception:
        pass

    # Fallback to localhost (when running directly on host)
    return "http://127.0.0.1:9222"


def is_cdp_available(base_url: Optional[str] = None) -> bool:
    """Fast check whether Chrome DevTools Protocol endpoint is reachable."""
    url = (base_url or resolve_cdp_host()).rstrip("/")
    try:
        with httpx.Client(timeout=1.5) as client:
            resp = client.get(f"{url}/json/version")
            return resp.status_code == 200
    except Exception:
        return False


async def _send_cdp_cmd(ws, msg_id: int, method: str, params: dict) -> dict:
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data


async def fetch_via_cdp_async(
    url: str,
    base_url: Optional[str] = None,
    timeout: float = 20.0,
    wait_seconds: float = 3.5,
    wait_selector: Optional[str] = None,
) -> Optional[str]:
    """
    Opens the URL in Chrome via CDP, waits for page load and Cloudflare challenge to pass,
    retrieves outerHTML, and closes the tab.
    """
    if websockets is None:
        logger.warning("websockets package not available for CDP")
        return None

    cdp_base = (base_url or resolve_cdp_host()).rstrip("/")
    tab_id = None
    client = httpx.AsyncClient(timeout=timeout)

    try:
        # 1. Create a new tab navigating to target URL
        create_resp = await client.put(f"{cdp_base}/json/new?{url}")
        if create_resp.status_code != 200:
            logger.warning("CDP new tab failed with status %d", create_resp.status_code)
            return None

        tab_data = create_resp.json()
        tab_id = tab_data.get("id")
        ws_url = tab_data.get("webSocketDebuggerUrl")

        if not ws_url:
            logger.warning("CDP did not return webSocketDebuggerUrl for tab %s", tab_id)
            return None

        # Replace localhost/127.0.0.1 with the netloc of cdp_base so docker container can reach host
        parsed_cdp = urllib.parse.urlparse(cdp_base)
        cdp_netloc = parsed_cdp.netloc
        if cdp_netloc:
            ws_url = re.sub(r"ws://(localhost|127\.0\.0\.1)(:\d+)?", f"ws://{cdp_netloc}", ws_url)

        # 2. Connect via WebSocket and wait for page to settle
        async with websockets.connect(ws_url, close_timeout=2.0, max_size=20 * 1024 * 1024) as ws:
            # Enable Runtime
            await _send_cdp_cmd(ws, 1, "Runtime.enable", {})

            start_time = asyncio.get_event_loop().time()
            final_html = None
            cmd_id = 10

            # Loop up to timeout seconds checking if page passed challenge
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                await asyncio.sleep(1.0)
                elapsed = asyncio.get_event_loop().time() - start_time

                cmd_id += 1
                title_resp = await _send_cdp_cmd(
                    ws, cmd_id, "Runtime.evaluate",
                    {"expression": "document.title", "returnByValue": True}
                )
                title_val = (
                    title_resp.get("result", {})
                    .get("result", {})
                    .get("value", "")
                    or ""
                )

                if "Just a moment" in title_val or not title_val:
                    continue

                if elapsed < wait_seconds:
                    continue

                # If wait_selector specified, check if element is present
                if wait_selector:
                    cmd_id += 1
                    sel_resp = await _send_cdp_cmd(
                        ws, cmd_id, "Runtime.evaluate",
                        {
                            "expression": f"Boolean(document.querySelector({json.dumps(wait_selector)}))",
                            "returnByValue": True,
                        }
                    )
                    if not sel_resp.get("result", {}).get("result", {}).get("value"):
                        continue

                # Get outerHTML
                cmd_id += 1
                html_resp = await _send_cdp_cmd(
                    ws, cmd_id, "Runtime.evaluate",
                    {
                        "expression": "document.documentElement.outerHTML",
                        "returnByValue": True,
                    }
                )
                final_html = (
                    html_resp.get("result", {})
                    .get("result", {})
                    .get("value")
                )
                if final_html and "Just a moment..." not in final_html:
                    break

            return final_html

    except Exception as exc:
        import traceback
        traceback.print_exc()
        logger.warning("CDP fetch error for %s: %s", url, exc)
        return None

    finally:
        # 3. Always close the tab to avoid leaking Chrome memory
        if tab_id:
            try:
                await client.put(f"{cdp_base}/json/close/{tab_id}")
            except Exception:
                pass
        await client.aclose()


def fetch_via_cdp(
    url: str,
    base_url: Optional[str] = None,
    timeout: float = 20.0,
    wait_seconds: float = 3.5,
    wait_selector: Optional[str] = None,
) -> Optional[str]:
    """Synchronous wrapper for fetch_via_cdp_async."""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    fetch_via_cdp_async(url, base_url, timeout, wait_seconds, wait_selector)
                )
                return future.result()
        return asyncio.run(
            fetch_via_cdp_async(url, base_url, timeout, wait_seconds, wait_selector)
        )
    except Exception as exc:
        logger.warning("fetch_via_cdp error: %s", exc)
        return None
