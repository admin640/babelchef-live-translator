import asyncio
from livekit.plugins import google

async def main():
    model = google.beta.realtime.RealtimeModel()
    print("Model initialized:", model.model)
    session = model.session()
    print("Session created")
    # We can't easily test connection without a real LiveKit context,
    # but we can check if it initializes without throwing credential errors.

asyncio.run(main())
