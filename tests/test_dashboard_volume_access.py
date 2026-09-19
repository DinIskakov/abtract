"""A Volume reload must not overlap another request's read or streamed response."""
import asyncio

from abtract.dashboard.app import VolumeAccessMiddleware


def test_volume_requests_are_exclusive_but_static_pages_are_not_blocked():
    async def scenario():
        first_entered, release_first, static_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        entered = []

        async def app(scope, receive, send):
            path = scope["path"]
            entered.append(path)
            if path == "/api/jobs/first":
                first_entered.set()
                await release_first.wait()
            if path == "/static/job.js":
                static_done.set()

        middleware = VolumeAccessMiddleware(app)
        async def call(path):
            await middleware({"type": "http", "path": path}, None, None)

        first = asyncio.create_task(call("/api/jobs/first"))
        await first_entered.wait()
        second = asyncio.create_task(call("/jobs/second"))
        screenshot = asyncio.create_task(call("/screenshots/r/e/1.png"))
        static = asyncio.create_task(call("/static/job.js"))
        await asyncio.wait_for(static_done.wait(), timeout=1)
        assert entered == ["/api/jobs/first", "/static/job.js"]
        release_first.set()
        await asyncio.gather(first, second, screenshot, static)
        assert entered[-2:] == ["/jobs/second", "/screenshots/r/e/1.png"]

    asyncio.run(scenario())
