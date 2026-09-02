from __future__ import annotations

import hashlib
import importlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any, cast

from .registry import Registry, RegistryError

Runner = Callable[[dict[str, Any]], dict[str, Any]]
RUNNER_NAMESPACE = "universal_agent_control_plane.runners."
logger = logging.getLogger(__name__)


class SkillExecutor:
    def __init__(self, registry: Registry, state: Any | None = None) -> None:
        self.registry = registry
        self.state = state
        self._modules: dict[str, tuple[ModuleType, int]] = {}
        self._digests: dict[str, str] = {}
        self._lock = RLock()

    def _audit(self, reference: str) -> str | None:
        digest = self.source_digest(reference)
        if self.state is not None:
            self.state.record_execution(reference, digest)
        return digest

    def run(self, skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        runner_reference = self.registry.runner_for(skill_name)
        runner = self._load_runner(runner_reference)
        digest = self._audit(runner_reference)
        logger.info(
            "Executing skill",
            extra={
                "fields": {
                    "skill": skill_name,
                    "runner": runner_reference,
                    "sourceDigest": digest,
                }
            },
        )
        result = runner(payload)
        return {"skill": skill_name, **result}

    def source_digest(self, reference: str) -> str | None:
        """Return the source hash of the module that will actually execute.

        Runners hot-reload when their source changes, so the module recorded
        at allow-list time is not necessarily the one that runs. Reporting the
        hash of the loaded source keeps audit records honest about which code
        executed.
        """
        module_name = reference.partition(":")[0]
        with self._lock:
            return self._digests.get(module_name)

    def run_reference(self, reference: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run an allow-listed runner reference directly.

        Hook handlers are declared as runner references rather than skill
        names, so they are validated by the same allow list without needing
        a SKILL.md document.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if reference not in self.registry.hook_handler_references():
            raise RegistryError(f"Handler is not allow-listed: {reference}")
        runner = self._load_runner(reference)
        digest = self._audit(reference)
        logger.info(
            "Running hook handler",
            extra={"fields": {"handler": reference, "sourceDigest": digest}},
        )
        return runner(payload)

    def _load_runner(self, reference: str) -> Runner:
        module_name, separator, function_name = reference.partition(":")
        if (
            separator != ":"
            or not module_name.startswith(RUNNER_NAMESPACE)
            or not self._valid_dotted_name(module_name)
            or not function_name.isidentifier()
        ):
            raise RegistryError(f"Invalid or disallowed runner reference: {reference}")

        with self._lock:
            module = self._load_or_reload_module(module_name)
            candidate = getattr(module, function_name, None)
            if not callable(candidate):
                raise RegistryError(f"Runner function is not callable: {reference}")
            return cast(Runner, candidate)

    def _load_or_reload_module(self, module_name: str) -> ModuleType:
        importlib.invalidate_caches()
        existing = self._modules.get(module_name)
        if existing is None:
            module = importlib.import_module(module_name)
            modified = self._module_mtime(module)
            self._modules[module_name] = (module, modified)
            self._digests[module_name] = self._source_hash(module)
            return module

        module, loaded_mtime = existing
        current_mtime = self._module_mtime(module)
        if current_mtime > loaded_mtime:
            cached_bytecode = getattr(module, "__cached__", None)
            if isinstance(cached_bytecode, str):
                Path(cached_bytecode).unlink(missing_ok=True)
            module = importlib.reload(module)
            current_mtime = self._module_mtime(module)
            self._modules[module_name] = (module, current_mtime)
            digest = self._source_hash(module)
            self._digests[module_name] = digest
            logger.info(
                "Reloaded skill runner",
                extra={"fields": {"module": module_name, "sourceDigest": digest}},
            )
        return module

    @staticmethod
    def _source_hash(module: ModuleType) -> str:
        source = getattr(module, "__file__", None)
        if not isinstance(source, str):
            raise RegistryError(f"Runner module has no source file: {module.__name__}")
        try:
            data = Path(source).read_bytes()
        except OSError as exc:
            raise RegistryError(f"Cannot read runner module: {module.__name__}") from exc
        return f"sha256:{hashlib.sha256(data).hexdigest()}"

    @staticmethod
    def _module_mtime(module: ModuleType) -> int:
        source = getattr(module, "__file__", None)
        if not isinstance(source, str):
            raise RegistryError(f"Runner module has no source file: {module.__name__}")
        try:
            return Path(source).stat().st_mtime_ns
        except OSError as exc:
            sys.modules.pop(module.__name__, None)
            raise RegistryError(f"Cannot inspect runner module: {module.__name__}") from exc

    @staticmethod
    def _valid_dotted_name(value: str) -> bool:
        return all(part.isidentifier() for part in value.split("."))
