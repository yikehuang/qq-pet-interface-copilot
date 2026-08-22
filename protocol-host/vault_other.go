//go:build !windows

package main

import "fmt"

func protectSession([]byte) ([]byte, error) {
	return nil, fmt.Errorf("secure session storage is currently Windows-only")
}

func unprotectSession([]byte) ([]byte, error) {
	return nil, fmt.Errorf("secure session storage is currently Windows-only")
}
