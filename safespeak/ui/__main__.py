"""python -m safespeak.ui   then open http://127.0.0.1:8765"""

import uvicorn

from safespeak.ui.server import app

uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
