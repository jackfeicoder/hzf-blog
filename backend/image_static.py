"""Keep legacy /uploads images readable with a 30-day browser cache."""
from fastapi.staticfiles import StaticFiles
from image_storage import CACHE_CONTROL


class ImageStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304) and path.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            response.headers["Cache-Control"] = CACHE_CONTROL
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response
