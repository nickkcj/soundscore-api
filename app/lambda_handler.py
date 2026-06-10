"""
AWS Lambda entrypoint.

Wraps the FastAPI app with Mangum so API Gateway (HTTP API) events
are translated into ASGI requests. The whole monolith runs inside
a single Lambda function ("serverless monolith").

lifespan="off": skips the startup warmup (DB/Redis/HTTP pools) to keep
cold starts fast. Connections are created lazily on first use and reused
while the Lambda container stays warm.
"""
from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
