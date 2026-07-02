#!/bin/bash
# Start script for Grid-X Worker

# Load configuration safely
if [ -f "worker_config.env" ]; then
    # Load variables from file, ignoring comments
    export $(grep -v '^#' worker_config.env | xargs)
fi

# Validate critical variables
if [ -z "$WORKER_EMAIL" ]; then
    echo "❌ ERROR: WORKER_EMAIL is not set in worker_config.env"
    exit 1
fi

echo "🚀 Starting Grid-X Worker"
echo "========================"
echo "Backend: ${BACKEND_URL}"
echo "Email:   ${WORKER_EMAIL}"

# Activate venv
source venv/bin/activate

# Run Worker
# 2>&1 | tee worker.log captures both stdout and stderr
python worker/main.py 2>&1 | tee worker.log
