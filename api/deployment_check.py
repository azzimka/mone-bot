"""Production diagnostics that never print configuration values or credentials."""
import asyncio
import sys
import traceback

async def check():
    try:
        from api.config import WebSettings
        from bot.database.schema import initialize_schema
        from sqlalchemy.ext.asyncio import create_async_engine
        config = WebSettings()
        print("Web settings valid. Bot username configured:", bool(config.TELEGRAM_BOT_USERNAME), flush=True)
        engine = create_async_engine(config.DATABASE_URL)
        print("Database driver:", engine.url.drivername, flush=True)
        await initialize_schema(engine)
        await engine.dispose()
        print("Database schema initialized successfully.", flush=True)
    except Exception as error:
        print("Deployment check failed:", type(error).__name__, flush=True)
        if hasattr(error, "errors"):
            for item in error.errors(): print("Invalid setting:", item.get("loc"), item.get("type"), flush=True)
        if isinstance(error, ModuleNotFoundError): print("Missing module:", error.name, flush=True)
        traceback.print_tb(error.__traceback__)
        sys.exit(1)

if __name__ == "__main__": asyncio.run(check())
