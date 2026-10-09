"""`python -m spark_body`: the sidecar Electron main spawns (stdio JSON-RPC, API.md §4)."""

import asyncio

from spark_body.app import main

asyncio.run(main())
