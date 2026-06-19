#!/usr/bin/env python3
"""One-shot Browser OS MCP call. Usage: python3 browseros_mcp.py <tool_name> [json_args]"""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = "http://127.0.0.1:9202/mcp"


async def main():
    if len(sys.argv) < 2:
        print("Usage: browseros_mcp.py <tool_name> [json_args]")
        sys.exit(1)

    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    try:
        async with streamable_http_client(url=MCP_URL) as (read, write, get_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments=args)

                # Print text content
                for c in result.content:
                    if hasattr(c, 'text') and c.text:
                        print(c.text)
                    elif hasattr(c, 'data') and c.data:
                        # Binary data - save to file or print hex
                        print(f"[binary data: {len(c.data)} bytes]")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
