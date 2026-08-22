package main

import (
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestSignerAdapters(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/custom_energy":
			fmt.Fprint(w, `{"code":0,"msg":"success","data":"0102"}`)
		case "/sign":
			_ = r.ParseForm()
			if _, err := hex.DecodeString(r.Form.Get("buffer")); err != nil {
				t.Fatalf("invalid buffer: %v", err)
			}
			if got := r.Form.Get("android_id"); got != "0123456789abcdef" {
				t.Fatalf("android_id = %q", got)
			}
			if got := r.Form.Get("guid"); got != "0102" {
				t.Fatalf("guid = %q", got)
			}
			if got := r.Form.Get("qimei36"); got != "qimei" {
				t.Fatalf("qimei36 = %q", got)
			}
			fmt.Fprint(w, `{"code":0,"msg":"","data":{"token":"03","extra":"04","sign":"05"}}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	signer := newSigner(server.URL)
	signer.setDevice("0123456789abcdef", []byte{1, 2}, "qimei")
	energy, err := signer.Energy(1, "810_9", "8.9.63", []byte{9})
	if err != nil || hex.EncodeToString(energy) != "0102" {
		t.Fatalf("energy: %x %v", energy, err)
	}
	sign, extra, token, err := signer.Sign(2, "123", "cmd", "qua", []byte{8})
	if err != nil || hex.EncodeToString(sign) != "05" || hex.EncodeToString(extra) != "04" || hex.EncodeToString(token) != "03" {
		t.Fatalf("sign result: %x %x %x %v", sign, extra, token, err)
	}
}
