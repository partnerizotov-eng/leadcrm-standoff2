"""Local runner and `run:app` WSGI target."""
import os

from app import app

application = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
