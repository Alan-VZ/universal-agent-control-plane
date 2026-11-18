"""Host-independent typed tools, bounded execution, durable records and replay.

MCP is a transport over these contracts; handlers are registered by trusted code.
"""

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SLOTS = threading.BoundedSemaphore(16)


def _check_schema(schema):
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in {"$ref", "$dynamicRef"} and not str(value).startswith("#"):
                raise ValueError("External schema references are unavailable")
            _check_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _check_schema(value)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]
    version: str = "1"
    output_schema: dict | None = None
    timeout: float = 30
    read_only: bool = False
    replay_safe: bool = False
    readiness: Callable[[], dict] | None = None
    source: str = "local"
    concurrency: int = 1
    _slots: Any = field(init=False, repr=False)

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", self.name):
            raise ValueError("Invalid tool name")
        if not 0.001 <= self.timeout <= 300 or not 1 <= self.concurrency <= 16:
            raise ValueError("Invalid execution limits")
        self.input_schema, self.output_schema = (
            deepcopy(self.input_schema),
            deepcopy(self.output_schema),
        )
        for schema in (self.input_schema, self.output_schema):
            if schema is not None:
                _check_schema(schema)
                Draft202012Validator.check_schema(schema)
        self._slots = threading.BoundedSemaphore(self.concurrency)

    def catalog(self):
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(self.input_schema),
            "outputSchema": deepcopy(self.output_schema),
            "version": self.version,
            "timeout_seconds": self.timeout,
            "read_only": self.read_only,
            "replay_safe": self.replay_safe,
            "source": self.source,
            "concurrency": self.concurrency,
        }


class ToolGateway:
    version = "uacp-tools-v1"

    def __init__(self, *, redact=None, event=None, database=None, history_limit=200):
        self.tools = {}
        self.redact = redact or (lambda value: value)
        self.event = event
        self.database = Path(database) if database else None
        self.history_limit = max(1, min(history_limit, 1000))
        self._records = {}
        self._lock = threading.RLock()
        if self.database:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS tool_executions (id TEXT PRIMARY KEY, record TEXT NOT NULL)"
                )

    def register(self, spec):
        if spec.name in self.tools:
            raise ValueError(f"Duplicate tool: {spec.name}")
        self.tools[spec.name] = spec

    def catalog(self):
        return [spec.catalog() for spec in self.tools.values()]

    def readiness(self, name):
        spec = self.tools.get(name)
        if spec is None:
            return {"ready": False, "status": "unknown_tool"}
        if spec.readiness is None:
            return {
                "ready": True,
                "status": "configured_unverified",
                "message": "Registered locally; no external operation was performed.",
            }
        try:
            return self.redact(spec.readiness())
        except Exception:  # noqa: BLE001 - isolate host readiness/event callbacks
            return {
                "ready": False,
                "status": "configuration_error",
                "message": "Check local tool configuration.",
            }

    def _emit(self, record, status):
        if self.event:
            try:
                self.event(
                    self.redact(
                        {
                            "execution_id": record["execution_id"],
                            "tool": record["tool"],
                            "status": status,
                        }
                    )
                )
            except Exception:  # noqa: BLE001, S110 - observer must not interrupt execution
                pass

    def get(self, execution_id):
        with self._lock:
            if execution_id in self._records:
                return deepcopy(self._records[execution_id])
        if self.database:
            with sqlite3.connect(self.database) as db:
                row = db.execute(
                    "SELECT record FROM tool_executions WHERE id=?", (execution_id,)
                ).fetchone()
            if row:
                return json.loads(row[0])
        raise KeyError("Unknown execution ID")

    def history(self):
        if self.database:
            with sqlite3.connect(self.database) as db:
                rows = db.execute(
                    "SELECT record FROM tool_executions ORDER BY rowid DESC LIMIT ?",
                    (self.history_limit,),
                ).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]
        with self._lock:
            return deepcopy(list(self._records.values()))

    def execute(self, name, arguments, *, timeout=None, replay_of=None):
        started = time.monotonic()
        record = {
            "execution_id": uuid.uuid4().hex,
            "gateway_version": self.version,
            "tool": str(name),
            "tool_version": None,
            "status": "queued",
            "ok": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0,
            "arguments": None,
            "result": None,
            "error": None,
            "replay_of": replay_of,
        }
        self._emit(record, "queued")

        def finish(status, code=None, message=None):
            record.update(
                status=status,
                ok=status == "succeeded",
                duration_ms=round((time.monotonic() - started) * 1000, 3),
            )
            if code:
                record["error"] = {"code": code, "message": str(message)[:2000]}
            record["arguments_redacted"] = record["arguments"] != self.redact(
                deepcopy(record["arguments"])
            )
            safe = self.redact(deepcopy(record))
            with self._lock:
                self._records[safe["execution_id"]] = safe
                while len(self._records) > self.history_limit:
                    self._records.pop(next(iter(self._records)))
            if self.database:
                try:
                    with sqlite3.connect(self.database) as db:
                        db.execute(
                            "INSERT INTO tool_executions VALUES (?,?)",
                            (safe["execution_id"], json.dumps(safe, allow_nan=False)),
                        )
                except (OSError, sqlite3.Error):
                    safe["record_save_error"] = (
                        "Execution finished, but the durable record could not be saved."
                    )
            self._emit(safe, status)
            return deepcopy(safe)

        spec = self.tools.get(name) if isinstance(name, str) else None
        if spec is None:
            return finish(
                "failed",
                "unknown_tool",
                "Tool is not registered. Select an advertised tool name; nothing was executed.",
            )
        record["tool_version"] = spec.version
        try:
            encoded = json.dumps(arguments, allow_nan=False)
            if len(encoded.encode()) > 65536:
                return finish("failed", "input_limit", "Tool arguments exceed 64 KiB.")
            args = json.loads(encoded)
            if not isinstance(args, dict):
                return finish(
                    "failed", "invalid_arguments", "Arguments must be a JSON object."
                )
            record["arguments"] = deepcopy(args)
            errors = sorted(
                Draft202012Validator(spec.input_schema).iter_errors(args),
                key=lambda e: str(list(e.path)),
            )
            if errors:
                error = errors[0]
                location = ".".join(str(p) for p in error.path) or "arguments"
                return finish(
                    "failed",
                    "invalid_arguments",
                    f"{location}: {error.validator} validation failed. Consult inputSchema; no tool was executed.",
                )
            deadline = (
                spec.timeout if timeout is None else min(float(timeout), spec.timeout)
            )
            if not math.isfinite(float(timeout if timeout is not None else deadline)):
                raise ValueError("Invalid timeout")
            if deadline <= 0:
                return finish("timed_out", "timeout", "No execution time remains.")
        except (ValueError, TypeError, OverflowError):
            return finish(
                "failed",
                "invalid_arguments",
                "Supply finite JSON arguments and a valid timeout.",
            )
        ready = self.readiness(name)
        if not ready.get("ready"):
            return finish(
                "failed", "not_ready", ready.get("message", ready.get("status"))
            )
        if not spec._slots.acquire(blocking=False):
            return finish(
                "failed",
                "busy",
                "This tool is still running; no duplicate operation was started.",
            )
        if not _SLOTS.acquire(blocking=False):
            spec._slots.release()
            return finish(
                "failed", "busy", "Execution capacity is full; nothing was started."
            )

        def invoke():
            try:
                return spec.handler(**deepcopy(args))
            finally:
                spec._slots.release()
                _SLOTS.release()

        pool = ThreadPoolExecutor(max_workers=1)
        self._emit(record, "running")
        future = pool.submit(invoke)
        try:
            result = future.result(timeout=deadline)
            if isinstance(result, str):
                if len(result.encode()) > 1048576:
                    return finish(
                        "failed", "output_limit", "Tool output exceeds 1 MiB."
                    )
                try:
                    parsed = json.loads(result)
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, dict):
                    result = parsed
            encoded = json.dumps(result, allow_nan=False)
            if len(encoded.encode()) > 1048576:
                return finish("failed", "output_limit", "Tool output exceeds 1 MiB.")
            record["result"] = result
            if isinstance(result, dict) and result.get("ok") is False:
                return finish(
                    "failed",
                    "tool_error",
                    "Tool reported a failure; inspect the recorded result.",
                )
            if isinstance(result, str) and result.lower().startswith(
                ("error:", "[error]", "fetch error", "calculator error")
            ):
                return finish(
                    "failed",
                    "tool_error",
                    "Tool reported a failure; inspect the recorded result.",
                )
            if spec.output_schema is not None and not Draft202012Validator(
                spec.output_schema
            ).is_valid(result):
                return finish(
                    "failed",
                    "invalid_output",
                    "Tool output does not match outputSchema.",
                )
            record["result_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
            return finish("succeeded")
        except FutureTimeout:
            record["may_still_be_running"] = True
            return finish(
                "timed_out",
                "timeout",
                "Deadline exceeded. Handler may still be running; do not retry a write automatically.",
            )
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary tool/transport failures
            return finish("failed", "execution_error", str(exc))
        finally:
            pool.shutdown(wait=False)

    def replay(self, execution_id):
        original = self.get(execution_id)
        spec = self.tools.get(original["tool"])
        if spec is None or not spec.replay_safe:
            raise ValueError(
                "Replay requires an explicitly replay-safe tool; writes and live network tools are excluded."
            )
        if (
            original["tool_version"] != spec.version
            or original["arguments"] is None
            or original.get("arguments_redacted")
        ):
            raise ValueError(
                "Replay requires the same tool version and non-redacted valid arguments."
            )
        return self.execute(spec.name, original["arguments"], replay_of=execution_id)
