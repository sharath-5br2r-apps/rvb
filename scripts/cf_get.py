#!/usr/bin/env python3
"""Cloudflare fetch helper with multiple bypass methods.

Priority order for HTML fetches:
  1. cf-bypasser (CFB)
  2. Trawl / 8191 solver
  3. FlareSolverr
  4. curl_cffi browser impersonation

Each method checks the response for Cloudflare challenge HTML before
accepting it; if detected, it is logged and the next method is tried.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Optional dependency: curl_cffi
# ---------------------------------------------------------------------------
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CFFI = True
except ImportError:
    cffi_requests = None
    _HAS_CFFI = False

MAX_RETRIES = 5
_TRAWL_READY: set = set()
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Cloudflare challenge / interstitial detection
# ---------------------------------------------------------------------------

def is_challenge(status_code: int, text: str, headers: dict = None) -> bool:
    """Return True when the response looks like a Cloudflare challenge page."""
    if status_code in (403, 503):
        return True
    if headers:
        h = {k.lower(): v for k, v in headers.items()} if isinstance(headers, dict) else headers
        if "cf-mitigated" in h:
            return True
    lower = (text or "").lower()
    return any(phrase in lower for phrase in (
        "just a moment...",
        "attention required!",
        "please wait... | cloudflare",
        "verify you are human",
        "turnstile",
        "_cf_chl_opt",
        "challenges.cloudflare.com",
        "__cf_chl_",
        "/cdn-cgi/challenge-platform/",
        "cdn-cgi/challenge-platform",
        "ray id:",
        "checking your browser",
        "cf-browser-verification",
    ))


def is_cf_html(text: str) -> bool:
    """Return True when *text* is an HTML page (CF interstitial or otherwise).

    Used to reject any method's response that delivers an HTML page instead
    of the real content, even when the server answers 200 OK.
    """
    if not text:
        return False
    lower = text.lstrip("\ufeff \t\r\n").lower()
    if is_challenge(200, text):
        return True
    return (
        lower.startswith("<!doctype html")
        or lower.startswith("<html")
        or lower.startswith("<head")
        or lower.startswith("<body")
        or "<meta http-equiv=" in lower[:4096]
        or "<title>" in lower[:4096]
    )


def is_valid_download(path: str, content_type: str = "") -> bool:
    """Reject HTML/error pages without assuming the downloaded file type."""
    try:
        content_type = (content_type or "").lower().split(";", 1)[0].strip()
        if content_type in {"text/html", "application/xhtml+xml"}:
            return False
        with open(path, "rb") as stream:
            header = stream.read(65536)
        if not header:
            return False
        sample = header.decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
        lower = sample.lower()
        if (
            is_challenge(200, sample)
            or lower.startswith("<!doctype html")
            or lower.startswith("<html")
            or lower.startswith("<head")
            or lower.startswith("<body")
            or "<meta http-equiv=" in lower[:4096]
        ):
            return False
        return True
    except OSError:
        return False


def html_interstitial(head: bytes, headers) -> bool:
    """True when a HTTP-200 body is an HTML page rather than the file requested."""
    ct = ""
    try:
        ct = (headers.get("content-type") or "").lower()
    except Exception:
        pass
    if "text/html" in ct or "application/xml" in ct:
        return True
    probe = (head or b"")[:64].lstrip()
    return probe[:1] == b"<"


# ---------------------------------------------------------------------------
# Success / exit helper
# ---------------------------------------------------------------------------

def ok(html: str, cf_cookies: str = "", user_agent: str = "") -> None:
    """Write the success JSON envelope and exit 0."""
    sys.stdout.write(json.dumps({
        "html": html,
        "cf_cookies": cf_cookies,
        "user_agent": user_agent or DEFAULT_UA,
    }))
    sys.exit(0)


# ---------------------------------------------------------------------------
# File-lock helper (serialise concurrent cf_get invocations)
# ---------------------------------------------------------------------------

def acquire_lock(lock_file: str):
    """Acquire an exclusive file lock to serialise concurrent cf_get calls."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(lock_file)), exist_ok=True)
        fd = open(lock_file, "w")
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:
            try:
                import msvcrt
                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
            except Exception:
                pass
        return fd
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Cookie helpers (used by curl_cffi path)
# ---------------------------------------------------------------------------

def load_cookies(session, cookie_file: str) -> None:
    """Load a Netscape cookie file into a curl_cffi Session."""
    if not cookie_file or not os.path.isfile(cookie_file):
        return
    try:
        with open(cookie_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 7 and not line.startswith("#"):
                    session.cookies.set(
                        parts[5], parts[6], domain=parts[0], path=parts[2]
                    )
    except Exception:
        pass

    # Also load a companion user-agent file if present.
    temp_dir = os.path.dirname(os.path.abspath(cookie_file))
    ua_path = os.path.join(temp_dir, "cf_ua.txt")
    if os.path.isfile(ua_path):
        try:
            with open(ua_path, "r", encoding="utf-8", errors="ignore") as f:
                ua = f.read().strip()
            if ua:
                session.headers["User-Agent"] = ua
        except Exception:
            pass


def cookies_to_header_str(session) -> str:
    """Return a 'name=value; ...' string from all cookies in the session jar."""
    try:
        jar = getattr(session.cookies, "jar", None)
        if jar is not None:
            return "; ".join(
                f"{c.name}={c.value}" for c in jar if c.name and c.value
            )
        if hasattr(session.cookies, "items"):
            return "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    except Exception:
        pass
    return ""


def save_cookies(session, cookie_file: str, user_agent: str = "") -> None:
    """Write session cookies back to a Netscape cookie file."""
    if not cookie_file:
        return
    try:
        temp_dir = os.path.dirname(os.path.abspath(cookie_file))
        os.makedirs(temp_dir, exist_ok=True)
        jar = getattr(session.cookies, "jar", None)
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            if jar is not None:
                for c in jar:
                    domain = getattr(c, "domain", "") or ""
                    flag = "TRUE" if domain.startswith(".") else "FALSE"
                    path = getattr(c, "path", "/") or "/"
                    secure = "TRUE" if getattr(c, "secure", False) else "FALSE"
                    expires = str(int(getattr(c, "expires", 0) or 0))
                    name = getattr(c, "name", "") or ""
                    val = getattr(c, "value", "") or ""
                    f.write(
                        f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{val}\n"
                    )
            elif hasattr(session.cookies, "items"):
                for name, val in session.cookies.items():
                    f.write(f"\tTRUE\t/\tFALSE\t0\t{name}\t{val}\n")

        if user_agent:
            with open(os.path.join(temp_dir, "cf_ua.txt"), "w", encoding="utf-8") as f:
                f.write(user_agent)

        cookie_header = cookies_to_header_str(session)
        if cookie_header:
            with open(os.path.join(temp_dir, "cf_cookies.txt"), "w", encoding="utf-8") as f:
                f.write(cookie_header)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# curl_cffi impersonation targets
# ---------------------------------------------------------------------------

def get_impersonate_targets() -> list:
    """Return supported curl_cffi browser profiles, newest/highest priority first."""
    targets = []
    try:
        from curl_cffi.requests import BrowserType
        import re

        def key(name):
            match = re.search(r"\d+", str(name))
            version = int(match.group()) if match else 0
            lowered = str(name).lower()
            family = (
                3 if "chrome" in lowered and "android" not in lowered
                else 2 if "safari" in lowered
                else 1 if "edge" in lowered
                else 0
            )
            return family, version

        members = [m.value for m in BrowserType if hasattr(m, "value")]
        for target in sorted(members, key=key, reverse=True):
            if target not in targets:
                targets.append(target)
    except Exception:
        pass

    for target in ("chrome", "safari"):
        if target not in targets:
            targets.append(target)
    return targets[:8]


# ---------------------------------------------------------------------------
# Method 1: cf-bypasser (CFB) sidecar  [highest priority]
# ---------------------------------------------------------------------------

def cfb_get(url: str, referer: str = "") -> None:
    """GET via cf-bypasser sidecar.

    On success with real content (no CF HTML detected) calls ok() and exits.
    If the response contains Cloudflare challenge/interstitial HTML, logs a
    warning and returns so the next method can be tried.
    """
    cfb_base = (os.environ.get("CFB_URL") or "").rstrip("/")
    if not cfb_base:
        return

    solver_url = cfb_base + "/html"
    params = urllib.parse.urlencode({"url": url})
    full_url = f"{solver_url}?{params}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(full_url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                headers = {k.lower(): v for k, v in resp.headers.items()}
            if resp.status == 200 and html:
                if is_challenge(resp.status, html, headers) or is_cf_html(html):
                    sys.stderr.write(
                        f"[cf_get] cfb attempt {attempt}: CF HTML detected "
                        f"(status={resp.status}); retrying.\n"
                    )
                else:
                    cf_cookies = headers.get("x-cf-bypasser-cookies", "").strip()
                    ua = headers.get("x-cf-bypasser-user-agent", "").strip() or DEFAULT_UA
                    ok(html, cf_cookies=cf_cookies, user_agent=ua)
        except Exception as exc:
            sys.stderr.write(f"[cf_get] cfb attempt {attempt} error: {exc}\n")
        if attempt < MAX_RETRIES:
            time.sleep(2)


# ---------------------------------------------------------------------------
# Method 2: Trawl / 8191 solver
# ---------------------------------------------------------------------------

def trawl_get(url: str, referer: str = "") -> None:
    """POST to a Trawl/8191 solver.

    On success with real content (no CF HTML detected) calls ok() and exits.
    If the response contains Cloudflare challenge/interstitial HTML, logs a
    warning and returns so the next method can be tried.
    """
    trawl_base = (os.environ.get("TRAWL_URL") or "").rstrip("/")
    if not trawl_base:
        return

    # Health-check once per base URL.
    if trawl_base not in _TRAWL_READY:
        health_url = trawl_base + "/health"
        ready = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(health_url, timeout=3) as health:
                    if 200 <= health.status < 500:
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not ready:
            sys.stderr.write("[cf_get] trawl: health check failed; skipping.\n")
            return
        _TRAWL_READY.add(trawl_base)

    solver_url = trawl_base + "/scrape"
    payload: dict = {"url": url, "maxTimeout": 60000, "skipHttp": True}
    if referer:
        payload["headers"] = {"Referer": referer}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                solver_url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=70) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(body)
            status = result.get("statusCode", 0)
            if isinstance(status, int) and 100 <= status < 400:
                html = result.get("html") or ""
                if not html:
                    pass
                elif is_challenge(status, html) or is_cf_html(html):
                    sys.stderr.write(
                        f"[cf_get] trawl attempt {attempt}: CF HTML detected "
                        f"(statusCode={status}); retrying.\n"
                    )
                else:
                    ua = result.get("userAgent") or DEFAULT_UA
                    cookies = "; ".join(
                        f"{c['name']}={c['value']}"
                        for c in result.get("cookies", [])
                        if "name" in c and "value" in c
                    )
                    ok(html, cf_cookies=cookies, user_agent=ua)
        except Exception as exc:
            sys.stderr.write(f"[cf_get] trawl attempt {attempt} error: {exc}\n")
        if attempt < MAX_RETRIES:
            time.sleep(2)


# ---------------------------------------------------------------------------
# Method 3: FlareSolverr
# ---------------------------------------------------------------------------

def fs_get(url: str, referer: str = "") -> None:
    """POST to FlareSolverr.

    On success with real content (no CF HTML detected) calls ok() and exits.
    If the response contains Cloudflare challenge/interstitial HTML, logs a
    warning and returns so the next method can be tried.
    """
    fs_base = (
        os.environ.get("FS_URL")
        or os.environ.get("FLARESOLVERR_URL")
        or os.environ.get("CF_BYPASS_SOLVER_FS_URL")
        or ""
    ).rstrip("/")
    if not fs_base:
        return

    solver_url = fs_base + "/v1"
    payload: dict = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
    if referer:
        payload["headers"] = {"Referer": referer}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                solver_url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=70) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(body)
            if result.get("status") == "ok":
                solution = result.get("solution", {})
                html = solution.get("response") or ""
                if not html:
                    pass
                elif is_challenge(200, html) or is_cf_html(html):
                    sys.stderr.write(
                        f"[cf_get] flaresolverr attempt {attempt}: CF HTML detected; retrying.\n"
                    )
                else:
                    cookies = "; ".join(
                        f"{c['name']}={c['value']}"
                        for c in solution.get("cookies", [])
                        if "name" in c and "value" in c
                    )
                    ua = solution.get("userAgent") or DEFAULT_UA
                    ok(html, cf_cookies=cookies, user_agent=ua)
        except Exception as exc:
            sys.stderr.write(f"[cf_get] flaresolverr attempt {attempt} error: {exc}\n")
        if attempt < MAX_RETRIES:
            time.sleep(2)


# ---------------------------------------------------------------------------
# Method 4: curl_cffi browser impersonation  [lowest priority]
# ---------------------------------------------------------------------------

def curl_cffi_get(url: str, cookie_file: str) -> None:
    """GET using curl_cffi browser impersonation.

    On success with real content (no CF HTML detected) calls ok() and exits.
    If the response contains Cloudflare challenge/interstitial HTML, logs a
    warning and tries the next impersonation profile.  Returns (without
    calling ok()) when all profiles are exhausted.
    """
    if not _HAS_CFFI:
        sys.stderr.write("[cf_get] curl_cffi not available; skipping.\n")
        return

    impersonate_targets = get_impersonate_targets()[:MAX_RETRIES]

    for imp in impersonate_targets:
        try:
            s = cffi_requests.Session(impersonate=imp)
            load_cookies(s, cookie_file)
            resp = s.get(url, timeout=15, allow_redirects=True)
            if is_challenge(resp.status_code, resp.text,
                            dict(getattr(resp, "headers", {}))):
                sys.stderr.write(
                    f"[cf_get] curl_cffi ({imp}): CF challenge page "
                    f"(status={resp.status_code}); trying next profile.\n"
                )
                continue
            if is_cf_html(resp.text):
                sys.stderr.write(
                    f"[cf_get] curl_cffi ({imp}): CF HTML interstitial detected "
                    f"(status={resp.status_code}); trying next profile.\n"
                )
                continue
            if resp.status_code == 200 and resp.text:
                cf_cookies = cookies_to_header_str(s)
                save_cookies(s, cookie_file)
                ok(resp.text, cf_cookies=cf_cookies, user_agent=DEFAULT_UA)
        except Exception as exc:
            sys.stderr.write(f"[cf_get] curl_cffi ({imp}) error: {exc}\n")
            continue


# ---------------------------------------------------------------------------
# Download helper (used by the "download" subcommand)
# ---------------------------------------------------------------------------

def effective_url(resp, fallback: str) -> str:
    """The URL a response actually landed on after redirects."""
    try:
        u = str(getattr(resp, "url", "") or "")
    except Exception:
        u = ""
    return u or fallback


def solve_challenge(url: str, session) -> tuple:
    """Ask the configured CF solver sidecar for clearance cookies."""
    solver_url = os.getenv("CF_SOLVER_URL", "http://localhost:8000").rstrip("/")
    try:
        resp = cffi_requests.get(
            f"{solver_url}/cookies", params={"url": url}, timeout=60
        )
        if resp.status_code == 200:
            data = resp.json()
            cookies = data.get("cookies", {})
            user_agent = data.get("user_agent", "")
            parsed_host = urllib.parse.urlparse(url).hostname or ""
            parts = parsed_host.split(".")
            default_domain = (
                f".{'.'.join(parts[-2:])}" if len(parts) >= 2 else parsed_host
            )
            if isinstance(cookies, dict):
                for k, v in cookies.items():
                    session.cookies.set(k, v, domain=default_domain)
            elif isinstance(cookies, list):
                for c in cookies:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        c_domain = c.get("domain") or default_domain
                        c_path = c.get("path", "/")
                        session.cookies.set(
                            c["name"], c["value"], domain=c_domain, path=c_path
                        )
            if user_agent:
                session.headers["User-Agent"] = user_agent
            return True, user_agent
    except Exception as e:
        sys.stderr.write(f"[cf_get] solver error at {solver_url}: {e}\n")
    return False, ""


def download_file(url: str, dest_path: str, referer: str = "", cookie_file: str = "") -> bool:
    """Download *url* to *dest_path*, handling Cloudflare interstitials."""
    if not _HAS_CFFI:
        sys.stderr.write("[cf_get] curl_cffi not available; cannot download.\n")
        return False

    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    temp_dest = f"{dest_path}.part"
    impersonate_targets = get_impersonate_targets()[:MAX_RETRIES]

    for imp in impersonate_targets:
        try:
            s = cffi_requests.Session(impersonate=imp)
            load_cookies(s, cookie_file)
            headers = {}
            if referer:
                headers["Referer"] = referer

            resp = s.get(url, headers=headers, timeout=(10, 300),
                         stream=True, allow_redirects=True)
            resp_headers = dict(getattr(resp, "headers", {}))

            if is_challenge(resp.status_code, "", resp_headers):
                # Try without Referer first.
                if referer:
                    resp_no_ref = s.get(url, timeout=(10, 300),
                                        stream=True, allow_redirects=True)
                    if not is_challenge(resp_no_ref.status_code, "",
                                        dict(getattr(resp_no_ref, "headers", {}))):
                        resp = resp_no_ref
                        resp_headers = dict(getattr(resp, "headers", {}))

                if is_challenge(resp.status_code, "", resp_headers):
                    sys.stderr.write(
                        f"[cf_get] download ({imp}): CF challenge "
                        f"(status={resp.status_code}); requesting solver cookies.\n"
                    )
                    solved, ua = solve_challenge(effective_url(resp, url), s)
                    if not solved and referer:
                        solved, ua = solve_challenge(referer, s)
                    if solved:
                        save_cookies(s, cookie_file, ua)
                        resp = s.get(url, timeout=(10, 300),
                                     stream=True, allow_redirects=True)
                        resp_headers = dict(getattr(resp, "headers", {}))

            if resp.status_code == 200:
                rejected = False
                probing = True
                with open(temp_dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1048576):
                        if not chunk:
                            continue
                        if probing:
                            probing = False
                            if html_interstitial(chunk, resp_headers):
                                sys.stderr.write(
                                    f"[cf_get] download ({imp}): HTML interstitial "
                                    "detected in body; trying next profile.\n"
                                )
                                rejected = True
                                break
                        f.write(chunk)
                try:
                    resp.close()
                except Exception:
                    pass

                content_type = resp_headers.get("content-type", "")
                if rejected or not os.path.isfile(temp_dest) or os.path.getsize(temp_dest) == 0:
                    if os.path.isfile(temp_dest):
                        try:
                            os.remove(temp_dest)
                        except Exception:
                            pass
                    continue

                if is_valid_download(temp_dest, content_type):
                    if os.path.isfile(dest_path):
                        os.remove(dest_path)
                    os.rename(temp_dest, dest_path)
                    save_cookies(s, cookie_file)
                    return True

                if os.path.isfile(temp_dest):
                    os.remove(temp_dest)
        except Exception as exc:
            sys.stderr.write(f"[cf_get] download error ({imp}): {exc}\n")
            if os.path.isfile(temp_dest):
                try:
                    os.remove(temp_dest)
                except Exception:
                    pass
            continue

    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(2)

    # Subcommand: cf_get.py download <url> <dest> [referer] [cookie_file]
    if sys.argv[1] == "download":
        if len(sys.argv) < 4:
            sys.exit(2)
        dl_url = sys.argv[2]
        dest = sys.argv[3]
        referer = sys.argv[4] if len(sys.argv) > 4 else ""
        cookie_file = sys.argv[5] if len(sys.argv) > 5 else ""
        success = download_file(dl_url, dest, referer, cookie_file)
        sys.exit(0 if success else 1)

    url = sys.argv[1]
    cookie_file = sys.argv[2] if len(sys.argv) > 2 else ""
    lock_file = sys.argv[3] if len(sys.argv) > 3 else ""
    referer = sys.argv[4] if len(sys.argv) > 4 else ""

    # Serialise concurrent requests via an exclusive file lock.
    _lock_fd = acquire_lock(lock_file) if lock_file else None  # noqa: F841

    # Try methods in priority order.  Each method calls ok() on success
    # (which exits 0) or returns so the next method can be tried.
    # CF HTML / challenge detection happens inside every method.

    sys.stderr.write("[cf_get] trying cf-bypasser (CFB)...\n")
    cfb_get(url, referer)

    sys.stderr.write("[cf_get] CFB failed; trying Trawl.\n")
    trawl_get(url, referer)

    sys.stderr.write("[cf_get] Trawl failed; trying FlareSolverr.\n")
    fs_get(url, referer)

    sys.stderr.write("[cf_get] FlareSolverr failed; trying curl_cffi.\n")
    curl_cffi_get(url, cookie_file)

    sys.stderr.write("[cf_get] All methods exhausted; giving up.\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
