"""
File drop API calls.
"""

import os
import mimetypes

import requests as _requests

from .auth import get_csrf
from .helpers import err

CHUNK = 256 * 1024


def _report(command, msg):
    try:
        from cli.crash_reporter import report
        report(command, RuntimeError(msg))
    except Exception:
        pass


def _touch_session():
    try:
        from cli.session import SESSION_FILE
        SESSION_FILE.touch()
    except Exception:
        pass


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_file(host, session, filepath, key=None, expiry_days=None, password=None,
                is_test=False, schedule=None, webhook_url=None, notify=None,
                is_public=False, tags=None):
    """
    Upload a file using the prepare → direct-PUT → confirm flow.
    Returns the drop key string on success, None on failure.
    """
    from cli.progress import ProgressBar

    size         = os.path.getsize(filepath)
    filename     = os.path.basename(filepath)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # ── Step 1: prepare ───────────────────────────────────────────────────────
    payload = {
        "filename":     filename,
        "size":         size,
        "content_type": content_type,
    }
    if key:
        payload["key"] = key
    if expiry_days:
        payload["expiry_days"] = expiry_days
    if is_test:
        payload["is_test"] = True

    try:
        csrf = get_csrf(host, session)
        res  = session.post(
            f"{host}/upload/prepare/",
            json=payload,
            headers={"X-CSRFToken": csrf},
            timeout=30,
        )
        if not res.ok:
            msg = f"Prepare failed (HTTP {res.status_code})"
            _handle_error(res, "Prepare failed")
            _report("up", msg)
            return None
        prep = res.json()
        _touch_session()
    except Exception as e:
        err(f"Prepare error: {e}")
        raise

    presigned_url = prep["presigned_url"]
    drop_key      = prep["key"]

    # ── Step 2: stream file directly to B2 ───────────────────────────────────
    bar = ProgressBar(size, label="uploading")

    class _ProgressFile:
        def __init__(self, path):
            self._f = open(path, "rb")
        def read(self, n=-1):
            chunk = self._f.read(n)
            if chunk:
                bar.update(len(chunk))
            return chunk
        def __len__(self):
            return size
        def close(self):
            self._f.close()

    pf = _ProgressFile(filepath)
    try:
        put_res = _requests.put(
            presigned_url,
            data=pf,
            headers={
                "Content-Type":   content_type,
                "Content-Length": str(size),
            },
            timeout=None,
        )
        if not put_res.ok:
            msg = f"B2 upload failed (HTTP {put_res.status_code})"
            err(f"{msg}: {put_res.text[:200]}")
            _report("up", msg)
            return None
    except Exception as e:
        err(f"Upload error: {e}")
        raise
    finally:
        pf.close()

    bar.done()

    # ── Step 3: confirm ───────────────────────────────────────────────────────
    confirm_payload = {
        "key":          drop_key,
        "filename":     filename,
        "content_type": content_type,
    }
    if expiry_days:
        confirm_payload["expiry_days"] = expiry_days
    if password:
        confirm_payload["password"] = password
    if is_test:
        confirm_payload["is_test"] = True
    if schedule:
        confirm_payload["schedule"] = schedule
    if webhook_url:
        confirm_payload["webhook_url"] = webhook_url
    if notify:
        confirm_payload["notify"] = notify
    if is_public:
        confirm_payload["is_public"] = True
    if tags:
        confirm_payload["tags"] = tags

    try:
        csrf = get_csrf(host, session)
        res  = session.post(
            f"{host}/upload/confirm/",
            json=confirm_payload,
            headers={"X-CSRFToken": csrf},
            timeout=30,
        )
        if res.ok:
            _touch_session()
            return res.json().get("key")
        msg = f"Confirm failed (HTTP {res.status_code})"
        _handle_error(res, "Confirm failed")
        _report("up", msg)
    except Exception as e:
        err(f"Confirm error: {e}")
        raise

    return None


# ── Download ──────────────────────────────────────────────────────────────────

def get_file(host, session, key, password=''):
    """
    Fetch a file drop.

    Returns:
      ('file', (bytes_content, filename)) — success
      ('password_required', None)         — password needed / wrong password
      (None, None)                        — not found, expired, or error
    """
    from cli.progress import ProgressBar

    headers = {"Accept": "application/json"}
    if password:
        headers["X-Drop-Password"] = password

    try:
        res = session.get(
            f"{host}/{key}/",
            headers=headers,
            timeout=30,
        )

        if res.status_code == 401:
            return 'password_required', None

        if not res.ok:
            _handle_http_error(res, key)
            return None, None

        _touch_session()

        data = res.json()
        if data.get("kind") != "file":
            err(f"/{key}/ is not a file drop.")
            return None, None

        filename = data.get("filename", key)
        filesize = data.get("filesize", 0)

        b2_url = data.get("presigned_url")

        if not b2_url:
            download_path = data.get("download")
            if not download_path:
                err(f"No download URL in response for /{key}/.")
                _report("get", "missing both presigned_url and download fields")
                return None, None

            dl_res = session.get(
                f"{host}{download_path}",
                timeout=10,
                allow_redirects=False,
            )
            if dl_res.status_code == 401:
                return 'password_required', None
            if dl_res.status_code in (301, 302, 303, 307, 308):
                b2_url = dl_res.headers["Location"]
            elif dl_res.ok:
                return "file", (dl_res.content, filename)
            else:
                msg = f"Download redirect failed (HTTP {dl_res.status_code})"
                err(f"{msg}.")
                _report("get", msg)
                return None, None

        bar        = ProgressBar(max(filesize, 1), label="downloading")
        chunks     = []
        downloaded = 0
        retries    = 3

        for attempt in range(retries + 1):
            req_headers = {}
            if downloaded:
                req_headers["Range"] = f"bytes={downloaded}-"
            try:
                with _requests.get(b2_url, stream=True, timeout=30,
                                   headers=req_headers) as stream:
                    if stream.status_code not in (200, 206):
                        msg = f"B2 download failed (HTTP {stream.status_code})"
                        err(f"{msg}.")
                        _report("get", msg)
                        return None, None
                    for chunk in stream.iter_content(chunk_size=CHUNK):
                        if chunk:
                            chunks.append(chunk)
                            downloaded += len(chunk)
                            bar.update(len(chunk))
                break  # success — exit retry loop
            except (_requests.exceptions.ChunkedEncodingError,
                    _requests.exceptions.ConnectionError) as exc:
                if attempt < retries:
                    import time as _time
                    _time.sleep(1)
                    continue
                err(f"Download failed after {retries + 1} attempts: {exc}")
                return None, None

        bar.done()
        return "file", (b"".join(chunks), filename)

    except Exception as e:
        err(f"Get error: {e}")
        raise


def _handle_error(res, prefix):
    try:
        msg = res.json().get("error", res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f"{prefix}: {msg}")


def _handle_http_error(res, key):
    if res.status_code == 404:
        err(f"Drop /{key}/ not found.")
    elif res.status_code == 410:
        err(f"Drop /{key}/ has expired.")
    else:
        msg = f"Server returned {res.status_code}"
        err(f"{msg}.")
        _report("get", msg)


# ── Remote URL upload ─────────────────────────────────────────────────────────

def upload_from_url(host, session, url, key=None, expiry_days=None,
                    password=None, is_test=False, schedule=None,
                    webhook_url=None, notify=None, is_public=False, tags=None):
    """
    Ask the server to fetch a URL and store it as a file drop.
    Returns (key, filename, filesize) on success, None on failure.
    """
    payload = {"url": url}
    if key:
        payload["key"] = key
    if expiry_days:
        payload["expiry_days"] = expiry_days
    if password:
        payload["password"] = password
    if is_test:
        payload["is_test"] = True
    if schedule:
        payload["schedule"] = schedule
    if webhook_url:
        payload["webhook_url"] = webhook_url
    if notify:
        payload["notify"] = notify
    if is_public:
        payload["is_public"] = True
    if tags:
        payload["tags"] = tags

    try:
        csrf = get_csrf(host, session)
        res = session.post(
            f"{host}/upload/from-url/",
            json=payload,
            headers={"X-CSRFToken": csrf},
            timeout=120,  # server-side fetch can take a while
        )
        if not res.ok:
            _handle_error(res, "Remote upload failed")
            _report("up", f"upload_from_url HTTP {res.status_code}")
            return None
        _touch_session()
        data = res.json()
        return data.get("key"), data.get("filename", ""), data.get("filesize", 0)
    except Exception as e:
        err(f"Remote upload error: {e}")
        raise