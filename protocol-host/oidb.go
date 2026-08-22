package main

import (
	"fmt"

	"github.com/Mrs4s/MiraiGo/client/pb/oidb"
	"github.com/RomiChan/protobuf/proto"
)

type oidbSpec struct {
	Command int32
	Service int32
	Write   bool
}

var allowedOIDB = map[string]oidbSpec{
	"OidbSvcTrpcTcp.0x95e1_0": {38369, 0, false},
	"OidbSvcTrpcTcp.0x96f2_1": {38642, 1, false},
	"OidbSvcTrpcTcp.0x9949_1": {39241, 1, false},
	"OidbSvcTrpcTcp.0x9bf1_1": {39921, 1, false},
	"OidbSvcTrpcTcp.0x9bf2_1": {39922, 1, false},
	"OidbSvcTrpcTcp.0x9b60_1": {39776, 1, false},
	"OidbSvcTrpcTcp.0x9ab2_1": {39602, 1, false},
	"OidbSvcTrpcTcp.0x975a_1": {38746, 1, false},
	"OidbSvcTrpcTcp.0x99f2_1": {39410, 1, false},
	"OidbSvcTrpcTcp.0x96a4_1": {38564, 1, false},
	"OidbSvcTrpcTcp.0x976c_0": {38764, 0, false},
	"OidbSvcTrpcTcp.0x9ad4_1": {39636, 1, false},
	"OidbSvcTrpcTcp.0x985d_0": {39005, 0, false},
	"OidbSvcTrpcTcp.0x975f_1": {38751, 1, false},

	"OidbSvcTrpcTcp.0x975e_1": {38750, 1, true},
	"OidbSvcTrpcTcp.0x992d_1": {39213, 1, true},
	"OidbSvcTrpcTcp.0x99df_1": {39391, 1, true},
	"OidbSvcTrpcTcp.0x9bf3_1": {39923, 1, true},
	"OidbSvcTrpcTcp.0x9bd0_0": {39888, 0, true},
	"OidbSvcTrpcTcp.0x96a6_1": {38566, 1, true},
	"OidbSvcTrpcTcp.0x985b_0": {39003, 0, true},
	"OidbSvcTrpcTcp.0x9760_1": {38752, 1, true},
	"OidbSvcTrpcTcp.0x9c44_1": {40004, 1, true},
}

func packOIDB(command, service int32, body []byte) ([]byte, error) {
	return proto.Marshal(&oidb.OIDBSSOPkg{
		Command:       command,
		ServiceType:   service,
		Bodybuffer:    body,
		ClientVersion: "Android 8.9.63.11390",
	})
}

func unpackOIDB(raw []byte) ([]byte, error) {
	pkg := new(oidb.OIDBSSOPkg)
	if err := proto.Unmarshal(raw, pkg); err != nil {
		return nil, fmt.Errorf("decode OIDB envelope: %w", err)
	}
	if pkg.Result != 0 {
		return nil, fmt.Errorf("QQ server error %d: %s", pkg.Result, pkg.ErrorMsg)
	}
	if len(pkg.Bodybuffer) == 0 {
		return nil, fmt.Errorf("QQ server returned an empty OIDB body")
	}
	return pkg.Bodybuffer, nil
}

func validateOIDB(name string, command, service int32, write bool) error {
	spec, ok := allowedOIDB[name]
	if !ok {
		return fmt.Errorf("command is not allow-listed")
	}
	if spec.Command != command || spec.Service != service {
		return fmt.Errorf("command metadata does not match the allow-list")
	}
	if spec.Write != write {
		return fmt.Errorf("read/write classification does not match the allow-list")
	}
	return nil
}
