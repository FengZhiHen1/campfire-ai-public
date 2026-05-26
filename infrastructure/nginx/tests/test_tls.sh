#!/bin/bash
# =============================================================================
# DEPLOY-02: TLS Security Test
# Verifies that Nginx only accepts TLS 1.3 connections and rejects
# older protocol versions.
# Requires: Nginx container running with SSL configured.
# =============================================================================
set -e

NGINX_HOST="${NGINX_HOST:-localhost}"
NGINX_HTTPS_PORT="${NGINX_HTTPS_PORT:-8443}"
PASS_COUNT=0
FAIL_COUNT=0

pass() {
    echo "  PASS: $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "  FAIL: $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

echo "=== DEPLOY-02: TLS Security Test ==="
echo "Target: ${NGINX_HOST}:${NGINX_HTTPS_PORT}"
echo ""

# ------------------------------------------------------------------
# Test 1: TLS 1.3 connection succeeds
# ------------------------------------------------------------------
echo "[Test 1] TLS 1.3 connection should succeed"
TLS13_OUTPUT=$(echo | openssl s_client -connect "${NGINX_HOST}:${NGINX_HTTPS_PORT}" \
    -tls1_3 2>&1)
TLS13_EXIT_CODE=$?

echo "--- openssl output (first 20 lines) ---"
echo "$TLS13_OUTPUT" | head -20
echo "---"

if [ "$TLS13_EXIT_CODE" = "0" ]; then
    echo "$TLS13_OUTPUT" | grep -q "Server certificate" && {
        pass "TLS 1.3 connection established successfully"
    } || {
        fail "TLS 1.3 connection did not complete handshake"
    }
else
    fail "TLS 1.3 connection failed (exit code ${TLS13_EXIT_CODE})"
fi
echo ""

# ------------------------------------------------------------------
# Test 2: TLS 1.2 connection is rejected
# ------------------------------------------------------------------
echo "[Test 2] TLS 1.2 connection should be rejected"
TLS12_OUTPUT=$(echo | openssl s_client -connect "${NGINX_HOST}:${NGINX_HTTPS_PORT}" \
    -tls1_2 2>&1)
TLS12_EXIT_CODE=$?

echo "--- openssl output (first 20 lines) ---"
echo "$TLS12_OUTPUT" | head -20
echo "---"

# TLS 1.2 should fail — check for handshake failure alert
if [ "$TLS12_EXIT_CODE" != "0" ]; then
    if echo "$TLS12_OUTPUT" | grep -qiE "alert|handshake failure|no protocols available|wrong version number"; then
        pass "TLS 1.2 connection correctly rejected (handshake failure detected)"
    else
        pass "TLS 1.2 connection rejected (exit code ${TLS12_EXIT_CODE})"
    fi
else
    fail "TLS 1.2 connection was NOT rejected — server may accept insecure protocols"
fi
echo ""

# ------------------------------------------------------------------
# Test 3: TLS 1.1 connection is rejected
# ------------------------------------------------------------------
echo "[Test 3] TLS 1.1 connection should be rejected"
TLS11_OUTPUT=$(echo | openssl s_client -connect "${NGINX_HOST}:${NGINX_HTTPS_PORT}" \
    -tls1_1 2>&1)
TLS11_EXIT_CODE=$?

echo "--- openssl output (first 20 lines) ---"
echo "$TLS11_OUTPUT" | head -20
echo "---"

if [ "$TLS11_EXIT_CODE" != "0" ]; then
    if echo "$TLS11_OUTPUT" | grep -qiE "alert|handshake failure|no protocols available|wrong version number"; then
        pass "TLS 1.1 connection correctly rejected (handshake failure detected)"
    else
        pass "TLS 1.1 connection rejected (exit code ${TLS11_EXIT_CODE})"
    fi
else
    fail "TLS 1.1 connection was NOT rejected — server may accept insecure protocols"
fi
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "=== Results ==="
echo "Passed: ${PASS_COUNT}"
echo "Failed: ${FAIL_COUNT}"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "FAIL: TLS security tests detected issues."
    exit 1
else
    echo "All TLS security tests passed."
fi

echo ""
echo "=== TLS security tests complete ==="
