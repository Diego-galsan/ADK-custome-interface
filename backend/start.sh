#!/bin/bash

# Since you already have the dependencies in your ARIA environment,
# we'll skip pip install and go straight to running the server

echo "Starting backend server on http://localhost:8000"
echo "Make sure you're in your ARIA virtual environment"

# Start the backend server
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
