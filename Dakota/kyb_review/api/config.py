# api/config.py
# This file contains configuration constants for the FastMCP server.
DNS             = "127.0.0.1"
PORT            = 8010
SERVICE_NAME    = "kyb"
VERSION         = "v1.0.0" # Major.Minor.Patch
prefix          = f"/{SERVICE_NAME}/api/{VERSION}"
TEMP_DIR        = "temp"
JSON_DIR        = f"{TEMP_DIR}/json"
RAW_DIR         = f"{TEMP_DIR}/raw"