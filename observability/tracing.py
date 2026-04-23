"""Langfuse tracing helpers (compatible with langfuse 4.x).

Usage:
    from observability.tracing import observe, get_langfuse

    @observe(name="my.operation")
    def my_func(arg):
        ...

    # In tests/shutdown, flush pending events:
    get_langfuse().flush()
"""

import os
from functools import wraps
from typing import Callable

from dotenv import load_dotenv
from langfuse import Langfuse, observe as _lf_observe

load_dotenv()

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse:
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _langfuse


def observe(name: str | None = None, **kwargs) -> Callable:
    """Wraps langfuse @observe with an optional span name override."""
    def decorator(fn: Callable) -> Callable:
        span_name = name or fn.__qualname__
        return _lf_observe(name=span_name, **kwargs)(fn)
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
