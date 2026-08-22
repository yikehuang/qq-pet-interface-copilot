//go:build windows

package main

import (
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
)

type dataBlob struct {
	size uint32
	data *byte
}

var (
	crypt32            = windows.NewLazySystemDLL("crypt32.dll")
	cryptProtectData   = crypt32.NewProc("CryptProtectData")
	cryptUnprotectData = crypt32.NewProc("CryptUnprotectData")
	kernel32           = windows.NewLazySystemDLL("kernel32.dll")
	localFree          = kernel32.NewProc("LocalFree")
)

func makeBlob(data []byte) dataBlob {
	if len(data) == 0 {
		return dataBlob{}
	}
	return dataBlob{size: uint32(len(data)), data: &data[0]}
}

func readBlob(blob dataBlob) []byte {
	if blob.size == 0 || blob.data == nil {
		return nil
	}
	return append([]byte(nil), unsafe.Slice(blob.data, blob.size)...)
}

func protectSession(data []byte) ([]byte, error) {
	input := makeBlob(data)
	entropyBytes := []byte("QQPetInterfaceCopilot/session/v2")
	entropy := makeBlob(entropyBytes)
	var output dataBlob
	result, _, callErr := cryptProtectData.Call(
		uintptr(unsafe.Pointer(&input)), 0, uintptr(unsafe.Pointer(&entropy)),
		0, 0, 0x1, uintptr(unsafe.Pointer(&output)),
	)
	if result == 0 {
		return nil, fmt.Errorf("CryptProtectData: %w", callErr)
	}
	defer localFree.Call(uintptr(unsafe.Pointer(output.data)))
	return readBlob(output), nil
}

func unprotectSession(data []byte) ([]byte, error) {
	input := makeBlob(data)
	entropyBytes := []byte("QQPetInterfaceCopilot/session/v2")
	entropy := makeBlob(entropyBytes)
	var output dataBlob
	result, _, callErr := cryptUnprotectData.Call(
		uintptr(unsafe.Pointer(&input)), 0, uintptr(unsafe.Pointer(&entropy)),
		0, 0, 0x1, uintptr(unsafe.Pointer(&output)),
	)
	if result == 0 {
		return nil, fmt.Errorf("CryptUnprotectData: %w", callErr)
	}
	defer localFree.Call(uintptr(unsafe.Pointer(output.data)))
	return readBlob(output), nil
}
