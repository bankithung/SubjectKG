#!/usr/bin/env python3
"""Transport layer for TypeSafe's Jev (System One) model - stdlib only.

Jev answers *typed questions about state*: it returns a probability, a chosen option,
or a position on a scale - never prose. That makes it usable as a programming
primitive: the answers drop straight into profile.json fields and into `if`
statements, with no parsing step.

Three things this module buys us over a bare urllib call:

  batching     Many questions over one state cost one copy of the state. TypeSafe
               measured 12.2x cost and 10x latency savings from batching; every
               judgment workflow in jev_brain.py is written to exploit that.
  caching      Identical (state, questions) pairs are answered from a local disk
               cache. Re-running an audit over an unchanged graph is free.
  concurrency  Independent requests (one per edge, one per prompt) go out on a
               thread pool, so wall-clock time is bounded by the slowest call
               rather than the sum of all of them.

Read the docs at https://docs.typesafe.ai - the API contract lives at /api.md.
"""
import concurrent.futures
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".jev-cache"

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

# The API rejects a Choice with more than 255 options and a Score with fewer than 2
# or more than 10 levels. We clamp locally so a bad graph edit surfaces as our error
# rather than a 422 from the service.
MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS, MAX_SCORE_LEVELS = 2, 10


class JevError(RuntimeError):
    pass


# --------------------------------------------------------------------------- env


def load_api_key() -> str:
    """TYPESAFE_API_KEY from the environment, else from a .env file at the repo root.

    The key must never reach the browser: every Jev call in this project is made
    from the server process. .env is gitignored.
    """
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "TYPESAFE_API_KEY":
                return value.strip().strip("'\"")
    raise JevError(
        "No TYPESAFE_API_KEY found. Put it in SubjectKG/.env as\n"
        "  TYPESAFE_API_KEY=apikey_...\n"
        "or export it in your shell. See .env.example."
    )


# ---------------------------------------------------------------- question builders
# Thin constructors so callers never hand-write the wire format, and so the option
# limits are enforced at the point the question is built.


def noul(instructions: str, true: str, false: str) -> dict:
    """Probability that a condition holds. The answer is a single float 0..1.

    A Noul near 0.5 means "as likely yes as no" - it is NOT a medium intensity.
    Use one Noul per label when several labels can be true at once.
    """
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true, "false": false},
    }


def choice(instructions: str, options: dict) -> dict:
    """Pick exactly one option. Returns the pick, the full distribution, and confidence.

    `options` maps a stable machine id -> a description the model reads. The id is
    what our code branches on; the description is what carries the meaning, so it
    must stand on its own without the id.
    """
    if not options:
        raise JevError("choice() needs at least one option")
    if len(options) > MAX_CHOICE_OPTIONS:
        raise JevError(f"choice() has {len(options)} options; the API allows {MAX_CHOICE_OPTIONS}")
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score(instructions: str, levels: list) -> dict:
    """Position on an ordered scale. Returns a probability-weighted float, not a bucket.

    Each level must describe a concrete situation and stand on its own - "medium"
    tells the model nothing, "a procedural gap: knows what a fraction is but
    misapplies the addition rule" tells it everything.
    """
    if not MIN_SCORE_LEVELS <= len(levels) <= MAX_SCORE_LEVELS:
        raise JevError(f"score() needs {MIN_SCORE_LEVELS}-{MAX_SCORE_LEVELS} levels, got {len(levels)}")
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


# ----------------------------------------------------------------------- the client


class JevClient:
    """Cached, retrying, concurrent client for the System One endpoint."""

    def __init__(self, api_key=None, model=DEFAULT_MODEL, cache=True, timeout=60.0):
        self.api_key = api_key or load_api_key()
        self.model = model
        self.timeout = timeout
        self.cache_enabled = cache
        CACHE_DIR.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.stats = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0}

    # -- cache ------------------------------------------------------------------

    def _cache_path(self, payload: dict) -> Path:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return CACHE_DIR / (hashlib.sha256(blob).hexdigest()[:32] + ".json")

    # -- single request ---------------------------------------------------------

    def ask(self, state, questions: dict, max_retries=4) -> dict:
        """Answer every question in `questions` against one `state`, in one round trip.

        Questions in a batch cannot see one another's answers - they are scored
        independently against the same state. That independence is the whole point:
        it is what makes speculative fan-out safe (ask about several branches at
        once, use only the answers for the branch that turns out to apply).

        Returns the API response dict plus a `_meta` key with timing and cache info.
        """
        payload = {"state": state, "model": self.model, "questions": questions}
        cache_file = self._cache_path(payload)

        if self.cache_enabled and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                with self._lock:
                    self.stats["cache_hits"] += 1
                cached["_meta"] = {"ms": 0, "cached": True}
                return cached
            except (ValueError, OSError):
                pass  # a corrupt cache entry is not worth failing over; re-fetch

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        started = time.time()
        last_error = None

        for attempt in range(max_retries):
            request = urllib.request.Request(
                API_URL,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                last_error = f"HTTP {exc.code}: {detail}"
                # 429 (rate limited) and 529 (overloaded) are the documented
                # retryable codes; everything else is our bug and retrying it
                # would just burn quota to get the same answer.
                if exc.code not in (429, 529) or attempt == max_retries - 1:
                    with self._lock:
                        self.stats["errors"] += 1
                    raise JevError(last_error) from exc
                time.sleep((2 ** attempt) + random.random())
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = f"connection failed: {exc}"
                if attempt == max_retries - 1:
                    with self._lock:
                        self.stats["errors"] += 1
                    raise JevError(last_error) from exc
                time.sleep((2 ** attempt) + random.random())
        else:  # pragma: no cover - loop always breaks or raises
            raise JevError(last_error or "exhausted retries")

        elapsed_ms = int((time.time() - started) * 1000)
        usage = result.get("usage", {})
        with self._lock:
            self.stats["calls"] += 1
            self.stats["input_tokens"] += usage.get("input_tokens", 0)
            self.stats["output_tokens"] += usage.get("output_tokens", 0)

        if self.cache_enabled:
            try:
                cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass  # an unwritable cache degrades speed, never correctness

        result["_meta"] = {"ms": elapsed_ms, "cached": False}
        return result

    # -- many requests ----------------------------------------------------------

    def ask_many(self, jobs, workers=8):
        """Run independent (state, questions) jobs concurrently, preserving order.

        Use this when the *states* differ - one per prompt, one per graph edge.
        When the state is shared, batch the questions into a single `ask` instead:
        that pays for the state once rather than once per question.

        Each result is {"ok": True, "result": ...} or {"ok": False, "error": ...};
        one failed edge must not sink a 289-edge audit.
        """
        jobs = list(jobs)
        if not jobs:
            return []
        results = [None] * len(jobs)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            futures = {
                pool.submit(self.ask, state, questions): index
                for index, (state, questions) in enumerate(jobs)
            }
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                try:
                    results[index] = {"ok": True, "result": future.result()}
                except Exception as exc:  # noqa: BLE001 - surfaced per-job to the caller
                    results[index] = {"ok": False, "error": str(exc)}
        return results


# --------------------------------------------------------------- answer accessors
# The API returns a tagged union per answer. These readers keep the workflow code
# free of shape checks and give one place to adapt if the contract moves.


def read_noul(answer: dict) -> float:
    return float(answer.get("noul", 0.0))


def read_choice(answer: dict):
    """-> (picked_id, confidence, {option_id: probability})"""
    return (
        answer.get("choice"),
        float(answer.get("confidence", 0.0)),
        answer.get("probabilities", {}) or {},
    )


def read_score(answer: dict):
    """-> (position_on_scale, confidence, {level_index: probability})

    The score is probability-weighted, so 1.02 over levels [slip, procedural,
    conceptual] means "solidly procedural" while 1.5 means the model is genuinely
    torn between procedural and conceptual. Rounding it to an integer throws away
    the most useful part of the answer.
    """
    return (
        float(answer.get("score", 0.0)),
        float(answer.get("confidence", 0.0)),
        answer.get("probabilities", {}) or {},
    )


if __name__ == "__main__":
    client = JevClient(cache=False)
    response = client.ask(
        "A student wrote: 1/2 + 1/3 = 2/5",
        {
            "misconception": choice(
                "Which error did this student make?",
                {
                    "added_across": "Added numerators together and denominators together, "
                                    "treating the fraction as two independent whole numbers",
                    "arithmetic_slip": "Used the right method but miscalculated",
                    "correct": "The answer is right",
                },
            ),
            "depth": score(
                "How deep is the underlying gap?",
                [
                    "A slip; the student understands the concept",
                    "A procedural gap; knows what a fraction is but misapplies the addition rule",
                    "A conceptual gap; does not understand what a fraction represents",
                ],
            ),
        },
    )
    print(json.dumps(response, indent=2))
