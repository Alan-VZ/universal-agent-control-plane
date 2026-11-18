"""Persistent, explicit MCP connections for trusted host configuration."""

import asyncio
import concurrent.futures
import threading

from mcp import StdioServerParameters
from mcp.client import Client


class MCPConnection:
    def __init__(
        self, *, command=None, args=None, env=None, cwd=None, url=None, timeout=30
    ):
        if bool(command) == bool(url):
            raise ValueError("Configure either a stdio command or a server URL")
        if url:
            from urllib.parse import urlsplit

            parsed = urlsplit(url)
            if (
                parsed.username
                or parsed.password
                or parsed.fragment
                or not parsed.hostname
                or parsed.scheme not in {"https", "http"}
                or (
                    parsed.scheme == "http"
                    and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                )
                or any(
                    word in parsed.query.lower()
                    for word in ("token", "key", "password")
                )
            ):
                raise ValueError(
                    "Use a public HTTPS/loopback HTTP MCP URL without embedded credentials"
                )
        self.transport = url or StdioServerParameters(
            command=command, args=args or [], env=env or {}, cwd=cwd
        )
        self.timeout = timeout
        self.ready = threading.Event()
        self.error = None
        self.loop = None
        self.queue = None
        self.thread = threading.Thread(
            target=lambda: asyncio.run(self._serve()), daemon=True
        )
        self.thread.start()
        if not self.ready.wait(timeout):
            self.close()
            raise TimeoutError("MCP connection did not become ready")
        if self.error:
            raise RuntimeError(
                "MCP connection failed; check its trusted local configuration"
            ) from self.error

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        try:
            async with Client(
                self.transport, read_timeout_seconds=self.timeout
            ) as client:
                self.ready.set()
                while True:
                    item = await self.queue.get()
                    if item is None:
                        break
                    method, arguments, future = item
                    if future.cancelled():
                        continue
                    try:
                        if method == "list":
                            tools, cursor = [], None
                            for _ in range(20):
                                page = await client.list_tools(cursor=cursor)
                                tools.extend(
                                    tool.model_dump(by_alias=True, exclude_none=True)
                                    for tool in page.tools
                                )
                                cursor = page.next_cursor
                                if not cursor:
                                    break
                            else:
                                raise ValueError(
                                    "MCP tool catalog exceeded pagination limit"
                                )
                            value = tools
                        else:
                            value = await client.call_tool(
                                arguments[0],
                                arguments[1],
                                read_timeout_seconds=self.timeout,
                            )
                        if not future.cancelled():
                            future.set_result(value)
                    except Exception as exc:  # noqa: BLE001 - isolate arbitrary tool/transport failures
                        if not future.cancelled():
                            future.set_exception(exc)
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary tool/transport failures
            self.error = exc
            self.ready.set()

    def _request(self, method, arguments):
        if not self.thread.is_alive() or self.error:
            raise RuntimeError(
                "MCP connection is closed or failed; reconnect explicitly"
            )
        future = concurrent.futures.Future()
        self.loop.call_soon_threadsafe(
            self.queue.put_nowait, (method, arguments, future)
        )
        try:
            return future.result(self.timeout + 2)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(
                "MCP request timed out; remote effects may still be running"
            ) from None

    def discover(self):
        return self._request("list", None)

    def call(self, name, arguments):
        return self._request("call", (name, arguments))

    def close(self):
        if self.loop and self.queue and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.queue.put_nowait, None)
