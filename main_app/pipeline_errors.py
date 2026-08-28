"""
pipeline_errors.py

Builds user-facing error messages for the multi-agent quiz pipeline.

Two kinds of pipeline failures:

  1. EXACT — the failure is deterministically identified (e.g. a manifest
     validator lists the precise invalid fields). A single precise message
     is sufficient; no cause list is needed.

  2. AMBIGUOUS — multiple plausible root causes exist that the app cannot
     resolve on its own (CLI/network failures, an agent response that fails
     to parse, an empty candidate pool whose trigger is unknown). We present
     the failure plus an ORDERED list of probable causes — a chain of actions
     to check in order.
"""

from __future__ import annotations


def build_pipeline_error(
    headline: str,
    detail: str = "",
    causes: list[str] | None = None,
) -> str:
    """
    Formats a structured pipeline error message.

    Args:
        headline: one-line statement of what failed.
        detail:   exact evidence (e.g. validator errors) when available.
        causes:   ordered probable causes to check, used only when the exact
                  cause cannot be determined.

    Returns:
        Multi-line message. Empty sections are omitted.
    """
    parts: list[str] = [headline.strip()]

    if detail and detail.strip():
        parts.append(detail.strip())

    if causes:
        numbered = "\n".join(
            f"{i}. {c.strip()}" for i, c in enumerate(causes, start=1) if c.strip()
        )
        if numbered:
            parts.append(f"Possible causes (check in order):\n{numbered}")

    return "\n\n".join(parts)
