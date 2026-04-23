"""Langfuse tracing helpers (compatible with langfuse 4.x).

Usage:
    from agent.observability.tracing import observe, get_langfuse

    @observe(name="my.operation")
    def my_func(arg):
        ...

    # In tests/shutdown, flush pending events:
    get_langfuse().flush()
"""

import inspect
import json
import os
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from langfuse import Langfuse, observe as _lf_observe

load_dotenv()

_langfuse: Langfuse | None = None
_trace_lock = threading.Lock()
_TRACE_FILE = Path(__file__).parent.parent / "outputs" / "trace_log.jsonl"


def get_langfuse() -> Langfuse:
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _langfuse


def _write_trace_line(event: dict) -> None:
    """Append one JSON line to outputs/trace_log.jsonl. Never raises."""
    try:
        _TRACE_FILE.parent.mkdir(exist_ok=True)
        line = json.dumps(event, default=str)
        with _trace_lock:
            with open(_TRACE_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def record_span(name: str, elapsed_ms: float, status: str = "ok", **extra) -> None:
    """Write a single span entry to trace_log.jsonl (for inline use in route handlers)."""
    _write_trace_line({
        "span": name,
        "ts": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": round(elapsed_ms, 1),
        "status": status,
        **extra,
    })


def observe(name: str | None = None, **kwargs) -> Callable:
    """Wraps langfuse @observe and also writes every call to trace_log.jsonl."""
    def decorator(fn: Callable) -> Callable:
        span_name = name or fn.__qualname__

        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def _async_traced(*args, **kw):
                t0 = time.monotonic()
                event: dict = {
                    "span": span_name,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    result = await fn(*args, **kw)
                    event["status"] = "ok"
                    event["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
                    return result
                except Exception as exc:
                    event["status"] = "error"
                    event["error"] = str(exc)
                    event["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
                    raise
                finally:
                    _write_trace_line(event)
            return _lf_observe(name=span_name, **kwargs)(_async_traced)
        else:
            @wraps(fn)
            def _sync_traced(*args, **kw):
                t0 = time.monotonic()
                event: dict = {
                    "span": span_name,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    result = fn(*args, **kw)
                    event["status"] = "ok"
                    event["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
                    return result
                except Exception as exc:
                    event["status"] = "error"
                    event["error"] = str(exc)
                    event["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
                    raise
                finally:
                    _write_trace_line(event)
            return _lf_observe(name=span_name, **kwargs)(_sync_traced)

    return decorator


def trace_llm_generation(
    name: str,
    model: str,
    prompt: str,
    completion: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Log a standalone LLM generation to Langfuse (for calls outside @observe)."""
    lf = get_langfuse()
    trace = lf.trace(name=name)
    trace.generation(
        name=name,
        model=model,
        input=prompt,
        output=completion,
        usage={"input": input_tokens, "output": output_tokens},
    )
