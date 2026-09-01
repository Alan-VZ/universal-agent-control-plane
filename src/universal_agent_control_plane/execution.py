from __future__ import annotations

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
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._modules: dict[str, tuple[ModuleType, int]] = {}
        self._lock = RLock()

    def run(self, skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        runner_reference = self.registry.runner_for(skill_name)
        runner = self._load_runner(runner_reference)
        logger.info(
            "Executing skill",
            extra={"fields": {"skill": skill_name, "runner": runner_reference}},
        )
        result = runner(payload)
        return {"skill": skill_name, **result}

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
            logger.info(
                "Reloaded skill runner",
                extra={"fields": {"module": module_name}},
            )
        return module

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
