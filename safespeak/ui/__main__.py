"""python -m safespeak.ui   then open http://127.0.0.1:8765

Host and port: SAFESPEAK_UI_HOST / SAFESPEAK_UI_PORT (see config.py).
"""

import uvicorn

from safespeak import config
from safespeak.ui.server import app

if warning := config.exposure_warning(config.UI_HOST):
    print(warning, flush=True)
uvicorn.run(app, host=config.UI_HOST, port=config.UI_PORT, log_level="warning")
