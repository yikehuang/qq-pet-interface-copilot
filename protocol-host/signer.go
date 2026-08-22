package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

type signerClient struct {
	baseURL   string
	http      *http.Client
	mu        sync.RWMutex
	androidID string
	guid      string
	qimei36   string
}

type apiResult struct {
	Code int             `json:"code"`
	Msg  string          `json:"msg"`
	Data json.RawMessage `json:"data"`
}

type signPayload struct {
	Token string `json:"token"`
	Extra string `json:"extra"`
	Sign  string `json:"sign"`
}

func newSigner(baseURL string) *signerClient {
	return &signerClient{
		baseURL: strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		http:    &http.Client{Timeout: 20 * time.Second},
	}
}

func (s *signerClient) configured() bool { return s.baseURL != "" }

func (s *signerClient) setDevice(androidID string, guid []byte, qimei36 string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.androidID = androidID
	s.guid = hex.EncodeToString(guid)
	s.qimei36 = qimei36
}

func (s *signerClient) Energy(_ uint64, moduleID, _ string, salt []byte) ([]byte, error) {
	if !s.configured() {
		return nil, fmt.Errorf("Android qsign service is not configured")
	}
	query := url.Values{}
	query.Set("data", moduleID)
	query.Set("salt", hex.EncodeToString(salt))
	var result apiResult
	if err := s.get("/custom_energy?"+query.Encode(), &result); err != nil {
		return nil, err
	}
	if result.Code != 0 {
		return nil, fmt.Errorf("qsign energy error %d: %s", result.Code, result.Msg)
	}
	var encoded string
	if err := json.Unmarshal(result.Data, &encoded); err != nil {
		return nil, fmt.Errorf("decode qsign energy response: %w", err)
	}
	return hex.DecodeString(encoded)
}

func (s *signerClient) Sign(seq uint64, uin, command, qua string, body []byte) ([]byte, []byte, []byte, error) {
	if !s.configured() {
		return nil, nil, nil, fmt.Errorf("Android qsign service is not configured")
	}
	form := url.Values{}
	form.Set("uin", uin)
	form.Set("qua", qua)
	form.Set("cmd", command)
	form.Set("seq", strconv.FormatUint(seq, 10))
	form.Set("buffer", hex.EncodeToString(body))
	s.mu.RLock()
	form.Set("android_id", s.androidID)
	form.Set("guid", s.guid)
	form.Set("qimei36", s.qimei36)
	s.mu.RUnlock()
	request, err := http.NewRequest(http.MethodPost, s.baseURL+"/sign", strings.NewReader(form.Encode()))
	if err != nil {
		return nil, nil, nil, err
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	response, err := s.http.Do(request)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("qsign request failed: %w", err)
	}
	defer response.Body.Close()
	var result apiResult
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		return nil, nil, nil, fmt.Errorf("decode qsign response: %w", err)
	}
	if result.Code != 0 {
		return nil, nil, nil, fmt.Errorf("qsign error %d: %s", result.Code, result.Msg)
	}
	var payload signPayload
	if err := json.Unmarshal(result.Data, &payload); err != nil {
		return nil, nil, nil, fmt.Errorf("decode qsign payload: %w", err)
	}
	sign, err := hex.DecodeString(payload.Sign)
	if err != nil {
		return nil, nil, nil, err
	}
	extra, err := hex.DecodeString(payload.Extra)
	if err != nil {
		return nil, nil, nil, err
	}
	token, err := hex.DecodeString(payload.Token)
	return sign, extra, token, err
}

func (s *signerClient) get(path string, target any) error {
	response, err := s.http.Get(s.baseURL + path)
	if err != nil {
		return fmt.Errorf("qsign request failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("qsign HTTP status %d", response.StatusCode)
	}
	return json.NewDecoder(response.Body).Decode(target)
}
