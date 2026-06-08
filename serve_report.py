#!/usr/bin/env python3
"""
REGOG Web App Server — serves the full REGOG web application.
Run this, then open http://localhost:8080/ in your browser.

The web app provides:
  - Scan form (city, state, property type, price range)
  - Streaming scan results in real-time
  - Click-to-expand property details with score breakdown
  - Save/bookmark properties
  - Scan history
  - Dark theme with REGOG aesthetic
"""

import os
import sys

# Ensure web app is importable
sys.path.insert(0, os.path.dirname(__file__))

from web.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"╔══════════════════════════════════════╗")
    print(f"║   REGOG Web App                      ║")
    print(f"║   Open your browser to:              ║")
    print(f"║   http://localhost:{port}/              ║")
    print(f"╚══════════════════════════════════════╝")
    print(f"\nEnter a city and click SCAN to start finding deals.")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
