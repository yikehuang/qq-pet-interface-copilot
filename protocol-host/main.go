package main

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	qq "github.com/Mrs4s/MiraiGo/client"
	"github.com/Mrs4s/MiraiGo/wrapper"
)

const sessionMagic = "QQPET-HOST-DPAPI-1\x00"

type storedSession struct {
	Device json.RawMessage `json:"device"`
	Token  string          `json:"token"`
}

type host struct {
	mu          sync.RWMutex
	client      *qq.QQClient
	device      *qq.DeviceInfo
	qrImage     []byte
	qrSig       []byte
	loginState  string
	lastError   string
	sessionPath string
	signer      *signerClient
	writes      bool
	androidID   string
	legacyQR    bool
}

type oidbRequest struct {
	CommandName string `json:"command_name"`
	Command     int32  `json:"command"`
	SubCommand  int32  `json:"sub_command"`
	BodyBase64  string `json:"body_base64"`
	Write       bool   `json:"write"`
}

func main() {
	defaultData := filepath.Join(os.Getenv("LOCALAPPDATA"), "QQPetInterfaceCopilot", "protocol")
	listen := flag.String("listen", "127.0.0.1:17890", "loopback listen address")
	dataDir := flag.String("data-dir", defaultData, "session data directory")
	signerURL := flag.String("qsign-url", os.Getenv("QQPET_QSIGN_URL"), "Android qsign service URL")
	androidID := flag.String("android-id", os.Getenv("QQPET_ANDROID_ID"), "Android ID shared with the local qsign runtime")
	protocolJSON := flag.String("protocol-json", os.Getenv("QQPET_PROTOCOL_JSON"), "Android QQ protocol descriptor matching qsign")
	enableWrites := flag.Bool("enable-writes", false, "enable allow-listed state-changing OIDB calls")
	enableLegacyQR := flag.Bool("enable-legacy-qr", false, "research only: enable the obsolete MiraiGo Android QR flow")
	flag.Parse()
	if strings.TrimSpace(*protocolJSON) != "" {
		data, err := os.ReadFile(*protocolJSON)
		if err != nil {
			log.Fatalf("read Android protocol descriptor: %v", err)
		}
		if err := qq.UpdateAppVersion(qq.AndroidPhone, data); err != nil {
			log.Fatalf("load Android protocol descriptor: %v", err)
		}
	}
	if err := requireLoopback(*listen); err != nil {
		log.Fatal(err)
	}
	if err := os.MkdirAll(*dataDir, 0700); err != nil {
		log.Fatal(err)
	}
	signer := newSigner(*signerURL)
	wrapper.DandelionEnergy = signer.Energy
	wrapper.FekitGetSign = signer.Sign
	h := &host{
		loginState:  "offline",
		sessionPath: filepath.Join(*dataDir, "android-session.dat"),
		signer:      signer,
		writes:      *enableWrites,
		androidID:   strings.TrimSpace(*androidID),
		legacyQR:    *enableLegacyQR,
	}
	h.restoreSessionAsync()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/health", h.health)
	mux.HandleFunc("POST /v1/login/qr", h.loginQR)
	mux.HandleFunc("POST /v1/login/logout", h.logout)
	mux.HandleFunc("GET /v1/friends", h.friends)
	mux.HandleFunc("POST /v1/oidb", h.oidb)
	server := &http.Server{
		Addr:              *listen,
		Handler:           localOnly(mux),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       20 * time.Second,
		WriteTimeout:      25 * time.Second,
	}
	log.Printf("QQPetProtocolHost listening on http://%s", *listen)
	if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func requireLoopback(address string) error {
	hostName, _, err := net.SplitHostPort(address)
	if err != nil {
		return fmt.Errorf("invalid listen address: %w", err)
	}
	ip := net.ParseIP(hostName)
	if hostName != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return fmt.Errorf("protocol host may only listen on loopback")
	}
	return nil
}

func localOnly(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hostName, _, err := net.SplitHostPort(r.RemoteAddr)
		ip := net.ParseIP(hostName)
		if err != nil || ip == nil || !ip.IsLoopback() {
			writeError(w, http.StatusForbidden, "loopback_only", "only local clients are allowed")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func newAndroidClient(deviceData []byte, androidID string) (*qq.QQClient, *qq.DeviceInfo, error) {
	device := qq.GenRandomDevice()
	device.Protocol = qq.AndroidPhone
	if len(deviceData) != 0 {
		if err := device.ReadJson(deviceData); err != nil {
			return nil, nil, fmt.Errorf("load device identity: %w", err)
		}
		device.Protocol = qq.AndroidPhone
	} else if androidID != "" {
		device.AndroidId = []byte(androidID)
		device.GenNewGuid()
	}
	client := qq.NewClientEmpty()
	client.UseDevice(device)
	return client, device, nil
}

func (h *host) health(w http.ResponseWriter, _ *http.Request) {
	version := qq.AndroidPhone.Version()
	h.mu.RLock()
	state := h.loginState
	lastError := h.lastError
	uin := ""
	if h.client != nil {
		uin = strconv.FormatInt(h.client.Uin, 10)
		if h.client.Online.Load() {
			state = "online"
		}
	}
	h.mu.RUnlock()
	signerState := "configured"
	if !h.signer.configured() {
		signerState = "missing"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":               true,
		"protocol_family":  "android_qq",
		"protocol_version": version.SortVersionName,
		"app_id":           version.AppId,
		"session_state":    state,
		"signer_state":     signerState,
		"uin":              uin,
		"last_error":       lastError,
		"writes_enabled":   h.writes,
		"android_id":       h.androidID,
		"login_capabilities": map[string]bool{
			"qr":              h.legacyQR,
			"password":        false,
			"session_restore": true,
		},
		"login_backend": "mirai_go_legacy",
		"login_help":    "旧式 Android 二维码已被 QQ 登录服务器拒绝；需要接入当前 Android 登录和签名实现",
	})
}

func (h *host) loginQR(w http.ResponseWriter, _ *http.Request) {
	if !h.legacyQR {
		writeError(w, http.StatusNotImplemented, "mobile_qr_unavailable", "旧式 Android 二维码登录已停用；当前服务器会拒绝该请求")
		return
	}
	h.mu.RLock()
	if h.client != nil && h.client.Online.Load() {
		h.mu.RUnlock()
		writeError(w, http.StatusConflict, "already_online", "QQ session is already online")
		return
	}
	if len(h.qrImage) != 0 && h.loginState == "waiting_scan" {
		image := append([]byte(nil), h.qrImage...)
		h.mu.RUnlock()
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "image_base64": base64.StdEncoding.EncodeToString(image)})
		return
	}
	h.mu.RUnlock()
	client, device, err := newAndroidClient(nil, h.androidID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "device_error", err.Error())
		return
	}
	h.signer.setDevice(string(device.AndroidId), device.Guid, device.QImei36)
	qr, err := client.FetchQRCode()
	if err != nil {
		client.Release()
		writeError(w, http.StatusBadGateway, "qr_fetch_failed", err.Error())
		return
	}
	h.mu.Lock()
	if h.client != nil {
		h.client.Release()
	}
	h.client = client
	h.device = device
	h.androidID = string(device.AndroidId)
	h.qrImage = append([]byte(nil), qr.ImageData...)
	h.qrSig = append([]byte(nil), qr.Sig...)
	h.loginState = "waiting_scan"
	h.lastError = ""
	h.mu.Unlock()
	go h.pollQR(client, qr.Sig)
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "image_base64": base64.StdEncoding.EncodeToString(qr.ImageData)})
}

func (h *host) pollQR(client *qq.QQClient, sig []byte) {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		result, err := client.QueryQRCodeStatus(sig)
		if err != nil {
			h.setLoginError(client, "二维码状态读取失败："+err.Error())
			return
		}
		switch result.State {
		case qq.QRCodeWaitingForScan:
			h.setStateFor(client, "waiting_scan")
		case qq.QRCodeWaitingForConfirm:
			h.setStateFor(client, "waiting_confirm")
		case qq.QRCodeConfirmed:
			login, err := client.QRCodeLogin(result.LoginInfo)
			if err != nil {
				h.setLoginError(client, "二维码登录失败："+err.Error())
				return
			}
			if login == nil || !login.Success {
				message := "服务器拒绝二维码登录"
				if login != nil && login.ErrorMessage != "" {
					message += "：" + login.ErrorMessage
				}
				h.setLoginError(client, message)
				return
			}
			h.mu.Lock()
			h.loginState = "online"
			h.lastError = ""
			h.qrImage = nil
			h.qrSig = nil
			h.mu.Unlock()
			if err := h.saveSession(client); err != nil {
				log.Printf("save encrypted session: %v", err)
			}
			return
		case qq.QRCodeTimeout, qq.QRCodeCanceled:
			h.setLoginError(client, "二维码已失效，请重新获取")
			return
		}
	}
}

func (h *host) setStateFor(client *qq.QQClient, state string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.client == client {
		h.loginState = state
	}
}

func (h *host) setLoginError(client *qq.QQClient, message string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.client == client {
		h.loginState = "error"
		h.lastError = message
		h.qrImage = nil
		h.qrSig = nil
	}
}

func (h *host) friends(w http.ResponseWriter, _ *http.Request) {
	client, ok := h.onlineClient(w)
	if !ok {
		return
	}
	if err := client.ReloadFriendList(); err != nil {
		writeError(w, http.StatusBadGateway, "friend_list_failed", err.Error())
		return
	}
	rows := make([]map[string]any, 0, len(client.FriendList))
	for _, friend := range client.FriendList {
		rows = append(rows, map[string]any{
			"uin": friend.Uin, "nickname": friend.Nickname, "remark": friend.Remark,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "friends": rows})
}

func (h *host) oidb(w http.ResponseWriter, r *http.Request) {
	client, ok := h.onlineClient(w)
	if !ok {
		return
	}
	var request oidbRequest
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 2<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_request", err.Error())
		return
	}
	if err := validateOIDB(request.CommandName, request.Command, request.SubCommand, request.Write); err != nil {
		writeError(w, http.StatusForbidden, "command_rejected", err.Error())
		return
	}
	if request.Write && !h.writes {
		writeError(w, http.StatusForbidden, "writes_disabled", "write operations are disabled until read-only verification succeeds")
		return
	}
	body, err := base64.StdEncoding.DecodeString(request.BodyBase64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", "body_base64 is invalid")
		return
	}
	envelope, err := packOIDB(request.Command, request.SubCommand, body)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "encode_failed", err.Error())
		return
	}
	raw, err := client.SendSsoPacket(request.CommandName, envelope)
	if err != nil {
		writeError(w, http.StatusBadGateway, "sso_failed", err.Error())
		return
	}
	responseBody, err := unpackOIDB(raw)
	if err != nil {
		writeError(w, http.StatusBadGateway, "oidb_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "body_base64": base64.StdEncoding.EncodeToString(responseBody)})
}

func (h *host) onlineClient(w http.ResponseWriter) (*qq.QQClient, bool) {
	h.mu.RLock()
	client := h.client
	h.mu.RUnlock()
	if client == nil || !client.Online.Load() {
		writeError(w, http.StatusConflict, "not_online", "mobile QQ session is not online")
		return nil, false
	}
	return client, true
}

func (h *host) logout(w http.ResponseWriter, _ *http.Request) {
	h.mu.Lock()
	if h.client != nil {
		h.client.Release()
	}
	h.client = nil
	h.device = nil
	h.qrImage = nil
	h.qrSig = nil
	h.loginState = "offline"
	h.lastError = ""
	h.mu.Unlock()
	_ = os.Remove(h.sessionPath)
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (h *host) saveSession(client *qq.QQClient) error {
	h.mu.RLock()
	device := h.device
	h.mu.RUnlock()
	if device == nil {
		return fmt.Errorf("device identity is missing")
	}
	plain, err := json.Marshal(storedSession{
		Device: device.ToJson(),
		Token:  base64.StdEncoding.EncodeToString(client.GenToken()),
	})
	if err != nil {
		return err
	}
	encrypted, err := protectSession(plain)
	if err != nil {
		return err
	}
	temporary := h.sessionPath + ".tmp"
	if err := os.WriteFile(temporary, append([]byte(sessionMagic), encrypted...), 0600); err != nil {
		return err
	}
	return os.Rename(temporary, h.sessionPath)
}

func (h *host) restoreSessionAsync() {
	go func() {
		raw, err := os.ReadFile(h.sessionPath)
		if errors.Is(err, os.ErrNotExist) {
			return
		}
		if err != nil || !strings.HasPrefix(string(raw), sessionMagic) {
			h.setRestoreError("加密会话文件无法读取")
			return
		}
		plain, err := unprotectSession(raw[len(sessionMagic):])
		if err != nil {
			h.setRestoreError("加密会话仅能由创建它的 Windows 用户读取")
			return
		}
		var session storedSession
		if err := json.Unmarshal(plain, &session); err != nil {
			h.setRestoreError("加密会话内容损坏")
			return
		}
		token, err := base64.StdEncoding.DecodeString(session.Token)
		if err != nil {
			h.setRestoreError("加密会话令牌损坏")
			return
		}
		client, device, err := newAndroidClient(session.Device, h.androidID)
		if err != nil {
			h.setRestoreError(err.Error())
			return
		}
		h.signer.setDevice(string(device.AndroidId), device.Guid, device.QImei36)
		h.mu.Lock()
		h.client = client
		h.device = device
		h.androidID = string(device.AndroidId)
		h.loginState = "connecting"
		h.mu.Unlock()
		if err := client.TokenLogin(token); err != nil {
			h.setLoginError(client, "快速登录失效，请重新扫码："+err.Error())
			return
		}
		h.setStateFor(client, "online")
	}()
}

func (h *host) setRestoreError(message string) {
	h.mu.Lock()
	h.loginState = "error"
	h.lastError = message
	h.mu.Unlock()
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"ok": false, "code": code, "message": message})
}
