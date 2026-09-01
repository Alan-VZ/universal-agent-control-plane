from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .logging_config import configure_logging
from .orchestration import AgentTarget
from .registry import RegistryError
from .server import DATA_DIR, executor, mcp, orchestrator, registry, state

logger = logging.getLogger(__name__)
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    host="127.0.0.1",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(
    title="Universal Agent Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)


class SkillRequest(BaseModel):
    skill: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class StateWriteRequest(BaseModel):
    namespace: str = Field(min_length=1, max_length=128)
    key: str = Field(min_length=1, max_length=128)
    value: Any


class OrchestrationRequest(SkillRequest):
    target: AgentTarget


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "registry": registry.validate()}


@app.get("/instructions")
def instructions(profile: str = "default") -> dict[str, str]:
    try:
        return {"profile": profile, "instructions": registry.instructions(profile)}
    except RegistryError as exc:
        raise _bad_request(exc) from exc


@app.get("/skills")
def skills() -> dict[str, list[dict[str, str]]]:
    return {
        "skills": [
            {"name": skill.name, "description": skill.description}
            for skill in registry.skills()
        ]
    }


@app.post("/execute")
def execute(request: SkillRequest) -> dict[str, Any]:
    try:
        return executor.run(request.skill, request.payload)
    except (RegistryError, ValueError) as exc:
        raise _bad_request(exc) from exc


@app.post("/copilot/skill")
def copilot_skill(request: SkillRequest) -> dict[str, Any]:
    return execute(request)


@app.get("/memory")
def memory(namespace: str, key: str) -> dict[str, Any]:
    try:
        return {"namespace": namespace, "key": key, "value": state.get(namespace, key)}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@app.post("/memory")
def write_memory(request: StateWriteRequest) -> dict[str, str]:
    try:
        result = state.put(request.namespace, request.key, request.value)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    logger.info(
        "Updated shared state through REST",
        extra={"fields": {"namespace": request.namespace, "key": request.key}},
    )
    return result


@app.post("/orchestrate")
def route(request: OrchestrationRequest) -> dict[str, Any]:
    try:
        return orchestrator.route(request.target, request.skill, request.payload)
    except (RegistryError, ValueError) as exc:
        raise _bad_request(exc) from exc


app.mount("/", mcp_app)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HTTP MCP and REST gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    if arguments.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The development API binds to localhost only")
    configure_logging(DATA_DIR)
    logger.info(
        "Starting HTTP gateway",
        extra={"fields": {"host": arguments.host, "port": arguments.port}},
    )
    uvicorn.run(app, host=arguments.host, port=arguments.port)


if __name__ == "__main__":
    main()
