#!/bin/bash
# =============================================================================
# DEPLOY-02: Nginx Configuration Syntax Test
# Validates that nginx.conf and all included configuration files pass
# the nginx -t syntax check. Run inside the container after docker build.
# =============================================================================
set -e

echo "=== DEPLOY-02: Nginx Configuration Syntax Test ==="

echo ""
echo "[1/2] Testing default configuration syntax..."
nginx -t
echo "PASS: Default configuration syntax is valid."

echo ""
echo "[2/2] Testing configuration with verbose output..."
nginx -t 2>&1 | tee /tmp/nginx_test_output.txt
if grep -q "syntax is ok" /tmp/nginx_test_output.txt && grep -q "test is successful" /tmp/nginx_test_output.txt; then
    echo "PASS: Nginx configuration test successful with verbose output."
else
    echo "FAIL: Nginx configuration test did not report success."
    cat /tmp/nginx_test_output.txt
    exit 1
fi

echo ""
echo "=== All Nginx configuration syntax tests passed ==="
