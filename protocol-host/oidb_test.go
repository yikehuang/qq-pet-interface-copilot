package main

import (
	"bytes"
	"testing"
)

func TestOIDBRoundTrip(t *testing.T) {
	body := []byte{1, 2, 3, 4}
	packed, err := packOIDB(38369, 0, body)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := unpackOIDB(packed)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(decoded, body) {
		t.Fatalf("body mismatch: %x", decoded)
	}
}

func TestOIDBAllowListRejectsMetadataMismatch(t *testing.T) {
	if err := validateOIDB("OidbSvcTrpcTcp.0x95e1_0", 38369, 1, false); err == nil {
		t.Fatal("expected service type mismatch")
	}
	if err := validateOIDB("OidbSvcTrpcTcp.0x95e1_0", 38369, 0, true); err == nil {
		t.Fatal("expected write classification mismatch")
	}
}

func TestListenAddressMustBeLoopback(t *testing.T) {
	if err := requireLoopback("127.0.0.1:17890"); err != nil {
		t.Fatal(err)
	}
	if err := requireLoopback("0.0.0.0:17890"); err == nil {
		t.Fatal("expected wildcard listen address to be rejected")
	}
}
