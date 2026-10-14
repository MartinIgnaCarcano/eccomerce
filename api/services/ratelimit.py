"""Rate-limiting best-effort en memoria, sin dependencias externas.

LIMITACION: el contador vive en la memoria del proceso. Con varios workers
de gunicorn cada uno tiene su propio contador y se reinicia al reiniciar el
proceso. El fix robusto es flask-limiter + Redis cuando se autorice infra.
"""

import time
import threading
from functools import wraps
from flask import request, jsonify

_lock = threading.Lock()
# clave -> lista de timestamps (epoch seg) dentro de la ventana
_hits = {}


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(max_requests, window_seconds=60):
    """Limita a max_requests por window_seconds por (IP, endpoint)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (_client_ip(), request.endpoint)
            now = time.time()
            with _lock:
                timestamps = [t for t in _hits.get(key, []) if now - t < window_seconds]
                if len(timestamps) >= max_requests:
                    _hits[key] = timestamps
                    return jsonify({"error": "Demasiados intentos, probá más tarde"}), 429
                timestamps.append(now)
                _hits[key] = timestamps
            return fn(*args, **kwargs)
        return wrapper
    return decorator
