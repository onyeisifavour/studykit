"""OpenCode Agent Session Manager for Pre-Quiz Diagnostic System.

Manages persistent CLI sessions for 5 background agents and the main chat.
All background agents run concurrently via ThreadPoolExecutor (up to 20 workers).
"""

from __future__ import annotations

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class TurnResult:
    """Container for all agent responses from a single turn."""

    main_reply: str = ""
    kg_report: str = ""
    miscon_report: str = ""
    mech_report: str = ""
    drill_report: str = ""
    errors: dict = field(default_factory=dict)


def call_agent(
    agent: str,
    session_id: Optional[str],
    message: str,
    model: str = "opencode/big-pickle",
    timeout: int = 120,
) -> tuple[str, Optional[str]]:
    """Call an OpenCode agent via CLI and return (response_text, session_id).

    Args:
        agent: Agent name (e.g. 'knowledge-graph-builder')
        session_id: Existing session ID to continue, or None for new session
        message: Message to send to the agent
        model: Model to use
        timeout: Timeout in seconds

    Returns:
        Tuple of (response text, new session_id)

    Raises:
        RuntimeError: If the agent call fails
        TimeoutError: If the call exceeds timeout
    """
    cmd = ["opencode", "run", "--agent", agent, "--model", model, "--format", "json"]
    if session_id:
        cmd.extend(["--session", session_id])
    cmd.append(message)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Agent '{agent}' timed out after {timeout}s")

    if result.returncode != 0:
        raise RuntimeError(
            f"Agent '{agent}' failed (exit {result.returncode}): {result.stderr[:500]}"
        )

    # Parse JSON lines output
    text_parts: list[str] = []
    new_session_id: Optional[str] = None

    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "sessionID" in event:
            new_session_id = event["sessionID"]

        part = event.get("part", {})
        if part.get("type") == "text":
            text_parts.append(part.get("text", ""))

    return "\n".join(text_parts).strip(), new_session_id


class AgentSessionManager:
    """Manages persistent sessions for all diagnostic agents.

    Usage:
        manager = AgentSessionManager(model='opencode/big-pickle')

        def on_complete(result: TurnResult):
            print(result.main_reply)   # → send to user
            print(result.kg_report)    # → save to notes

        manager.turn(
            main_message="Student: my answer",
            turn_number=2,
            student_msg="my answer",
            tutor_response="previous tutor reply",
            on_complete=on_complete,
        )
    """

    AGENTS = {
        "main": "pre-quiz_main_chat",
        "kg": "knowledge-graph-builder",
        "miscon": "misconception-classifier",
        "mech": "mechanism-evaluator",
        "drill": "drill-recommender",
    }

    def __init__(
        self,
        model: str = "opencode/big-pickle",
        max_workers: int = 5,
        timeout: int = 120,
    ):
        self.model = model
        self.timeout = timeout
        self._sessions: dict[str, Optional[str]] = {
            key: None for key in self.AGENTS
        }
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    def start(
        self,
        topics_message: str,
        student_greeting: str = "",
        on_complete: Optional[Callable[[TurnResult], None]] = None,
    ) -> TurnResult:
        """Start a new diagnostic session.

        Sends the START DIAGNOSTIC SESSION message to main chat.
        Background agents receive the greeting as their first message.

        Args:
            topics_message: The START DIAGNOSTIC SESSION block with topic paths
            student_greeting: Student's initial greeting (optional)
            on_complete: Callback when all agents finish (optional, blocking if None)

        Returns:
            TurnResult with main_reply containing the greeting
        """
        # Build messages for each agent
        messages = {}

        # Main chat gets the full start signal
        messages["main"] = topics_message

        # Background agents get the greeting as context
        if student_greeting:
            bg_msg = f"Turn 1:\nStudent: {student_greeting}\nTutor: null"
        else:
            bg_msg = "Turn 1:\nStudent: (session starting)\nTutor: null"
        for key in ["kg", "miscon", "mech", "drill"]:
            messages[key] = bg_msg

        result = self._call_all_parallel(messages)

        if on_complete:
            on_complete(result)
        return result

    def turn(
        self,
        main_message: str,
        turn_number: int,
        student_msg: str,
        tutor_response: str,
        on_complete: Optional[Callable[[TurnResult], None]] = None,
    ) -> TurnResult:
        """Process a single turn across all agents.

        Args:
            main_message: Message for the main chat agent
            turn_number: Current turn number (1-indexed)
            student_msg: What the student said
            tutor_response: What the tutor replied (None if no response yet)
            on_complete: Callback when all agents finish (optional, blocking if None)

        Returns:
            TurnResult with all agent responses
        """
        # Build messages for each agent
        messages = {}

        # Main chat gets the student message directly
        messages["main"] = main_message

        # Background agents get the formatted transcript
        tutor_str = tutor_response if tutor_response else "(no response yet)"
        bg_msg = f"Turn {turn_number}:\nStudent: {student_msg}\nTutor: {tutor_str}"
        for key in ["kg", "miscon", "mech", "drill"]:
            messages[key] = bg_msg

        result = self._call_all_parallel(messages)

        if on_complete:
            on_complete(result)
        return result

    def _call_all_parallel(self, messages: dict[str, str]) -> TurnResult:
        """Call all agents in parallel and collect results.

        Args:
            messages: Dict mapping agent keys to their messages

        Returns:
            TurnResult with all responses
        """
        result = TurnResult()
        futures = {}

        for key, msg in messages.items():
            agent_name = self.AGENTS[key]
            session_id = self._sessions[key]

            future = self._executor.submit(
                call_agent,
                agent=agent_name,
                session_id=session_id,
                message=msg,
                model=self.model,
                timeout=self.timeout,
            )
            futures[future] = key

        for future in as_completed(futures):
            key = futures[future]
            try:
                response, new_session_id = future.result()
                with self._lock:
                    self._sessions[key] = new_session_id

                if key == "main":
                    result.main_reply = response
                elif key == "kg":
                    result.kg_report = response
                elif key == "miscon":
                    result.miscon_report = response
                elif key == "mech":
                    result.mech_report = response
                elif key == "drill":
                    result.drill_report = response

            except Exception as e:
                result.errors[key] = str(e)

        return result

    def reset(self):
        """Clear all session IDs (start fresh)."""
        with self._lock:
            self._sessions = {key: None for key in self.AGENTS}

    def shutdown(self):
        """Shutdown the thread pool."""
        self._executor.shutdown(wait=False)
