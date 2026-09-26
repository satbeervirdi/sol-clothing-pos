#!/usr/bin/env python3
"""
ThreadFlow Clothing POS & CRM Launcher
Starts the FastAPI server with SQLite backend on http://localhost:8000
"""
import uvicorn
import sys
import os

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    print("==================================================================")
    print(" 🚀 THREADFLOW • Smart Clothing POS, CRM & Billing System")
    print("==================================================================")
    print(" • Local POS URL : http://localhost:8000")
    print(" • Network Access: http://0.0.0.0:8000 (Access from tablet/phone)")
    print(" • API Docs      : http://localhost:8000/docs")
    print(" • Database      : clothing_pos.db (SQLite with WAL mode)")
    print("==================================================================")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
