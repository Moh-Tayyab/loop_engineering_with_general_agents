#!/usr/bin/env bash
# Start GitHub MCP Server locally with maximum toolsets
# Requires Docker running

set -e

echo "Starting GitHub MCP Server with maximum toolsets..."

# Run the official GitHub MCP Server Docker image
# with all toolsets enabled and PAT authentication
docker run -d \
  -p 8085:8085 \
  -e GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:-}" \
  -e GITHUB_TOOLSETS="all" \
  -e GITHUB_READ_ONLY="false" \
  -e GITHUB_MCP_SERVER_NAME="loop-engineering-mcp" \
  ghcr.io/github/github-mcp-server

echo "MCP Server started on http://localhost:8085"
echo "View logs: docker logs -f github-mcp-server"
echo "Stop: docker rm -f github-mcp-server"