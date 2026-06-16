#!/bin/bash
cd "$(dirname "$0")"
echo "Starting ContentForge..."

# Kill any existing instance
lsof -ti:3002 | xargs kill -9 2>/dev/null

# Start server in background
npx next dev -p 3002 -H 0.0.0.0 &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..20}; do
  curl -s -o /dev/null http://127.0.0.1:3002 && break
  sleep 0.5
done

# Open browser
open http://127.0.0.1:3002

echo ""
echo "ContentForge running at http://127.0.0.1:3002"
echo "Press Ctrl+C to stop"
echo ""

# Keep alive until user kills it
wait $SERVER_PID
