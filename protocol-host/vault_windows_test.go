//go:build windows

package main

import (
	"bytes"
	"testing"
)

func TestDPAPIRoundTrip(t *testing.T) {
	plain := []byte("test-session-secret")
	encrypted, err := protectSession(plain)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(encrypted, plain) {
		t.Fatal("DPAPI output contains plaintext")
	}
	decoded, err := unprotectSession(encrypted)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(decoded, plain) {
		t.Fatalf("round trip mismatch: %q", decoded)
	}
}
