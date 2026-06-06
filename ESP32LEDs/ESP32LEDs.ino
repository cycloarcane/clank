#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoJson.h>

// HTTPS server from ESP-IDF, bundled with ESP32 Arduino core 3.x — no extra
// library to install.
#include <esp_https_server.h>

// TLS certificate + private key, as PEM strings.
// Generate before flashing:  python3 scripts/generate_esp32_cert.py --ip <device-ip>
// cert.h contains the private key and must never be committed (see .gitignore).
#include "cert.h"

// WiFi credentials + API key. Copy secrets.h.example to secrets.h and fill in.
// secrets.h is gitignored so credentials are never committed.
#include "secrets.h"

// baud 115200

// WiFi credentials (from secrets.h)
const char* ssid     = WIFI_SSID;
const char* password = WIFI_PASSWORD;

// Static IP on the host hotspot subnet. Fixed up front so the TLS certificate
// can pin this address before the device is ever flashed. gateway_IP is the
// host AP (NetworkManager "shared" default is 10.42.0.1).
IPAddress local_IP(10, 42, 0, 50);
IPAddress gateway_IP(10, 42, 0, 1);
IPAddress subnet_mask(255, 255, 255, 0);

// Shared API key (from secrets.h) — must match ESP32_API_KEY on the Python side.
// Leave empty ("") in secrets.h to disable authentication (not recommended).
const char* API_KEY = CLANK_API_KEY;

// mDNS hostname — device will be reachable at clank-led.local
const char* MDNS_HOSTNAME = "clank-led";

// LED pins — adjust based on your wiring
const int RED_LED_PIN   = 18;  // GPIO18
const int GREEN_LED_PIN = 23;  // GPIO23
const int BLUE_LED_PIN  = 16;  // GPIO16

httpd_handle_t server = NULL;

// ---------- rate limiting ----------
// Sliding-window limiter: at most RATE_LIMIT_MAX requests per
// RATE_LIMIT_WINDOW_MS. Applied to /led-control before authentication so
// it also throttles API-key brute-force attempts.
const int           RATE_LIMIT_MAX       = 60;       // requests per window
const unsigned long RATE_LIMIT_WINDOW_MS = 60000UL;  // 60 seconds

unsigned long requestTimes[RATE_LIMIT_MAX];
int           requestCount = 0;

// Returns true if a new request is allowed, recording it if so.
// Unsigned subtraction makes this correct across millis() overflow (~49 days).
bool rateLimitAllow() {
  unsigned long now = millis();

  int kept = 0;
  for (int i = 0; i < requestCount; i++) {
    if (now - requestTimes[i] < RATE_LIMIT_WINDOW_MS) {
      requestTimes[kept++] = requestTimes[i];
    }
  }
  requestCount = kept;

  if (requestCount >= RATE_LIMIT_MAX) return false;

  requestTimes[requestCount++] = now;
  return true;
}

// ---------- helpers ----------

// Returns true if the request carries a valid API key.
// Authentication is skipped when API_KEY is empty (dev/testing only).
// Uses a constant-time comparison to avoid leaking the key via timing.
bool isAuthenticated(httpd_req_t* req) {
  if (strlen(API_KEY) == 0) return true;

  size_t hlen = httpd_req_get_hdr_value_len(req, "X-API-Key");
  if (hlen == 0) return false;

  char provided[160];
  if (hlen >= sizeof(provided)) return false;
  if (httpd_req_get_hdr_value_str(req, "X-API-Key", provided, sizeof(provided)) != ESP_OK) {
    return false;
  }

  size_t keyLen  = strlen(API_KEY);
  size_t provLen = strlen(provided);

  // Constant-time compare: always scan the full key length and fold any
  // length mismatch into the result so timing does not reveal the key.
  unsigned char diff = (unsigned char)(provLen ^ keyLen);
  for (size_t i = 0; i < keyLen; i++) {
    char p = (i < provLen) ? provided[i] : 0;
    diff |= (unsigned char)(p ^ API_KEY[i]);
  }
  return diff == 0;
}

esp_err_t sendText(httpd_req_t* req, const char* status, const char* body) {
  httpd_resp_set_status(req, status);
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

// ---------- handlers ----------

esp_err_t handleHealth(httpd_req_t* req) {
  // Public endpoint — no auth required.
  // Clank discovery service checks GET /health for {"service":"clank-led"}.
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, "{\"service\":\"clank-led\",\"status\":\"ok\"}",
                         HTTPD_RESP_USE_STRLEN);
}

esp_err_t handleLedControl(httpd_req_t* req) {
  if (!rateLimitAllow()) {
    return sendText(req, "429 Too Many Requests", "Rate limit exceeded");
  }

  if (!isAuthenticated(req)) {
    return sendText(req, "401 Unauthorized", "Authentication failed");
  }

  // Read the request body (bounded — the command JSON is tiny).
  int total = req->content_len;
  if (total <= 0 || total > 255) {
    return sendText(req, "400 Bad Request", "No data received");
  }

  char buf[256];
  int received = 0;
  while (received < total) {
    int r = httpd_req_recv(req, buf + received, total - received);
    if (r <= 0) {
      if (r == HTTPD_SOCK_ERR_TIMEOUT) continue;
      return ESP_FAIL;
    }
    received += r;
  }
  buf[received] = '\0';

  StaticJsonDocument<200> doc;
  DeserializationError error = deserializeJson(doc, buf, received);
  if (error) {
    return sendText(req, "400 Bad Request", "Invalid JSON");
  }

  if (doc["action"] != "led_control") {
    return sendText(req, "400 Bad Request", "Unknown action");
  }

  const char* color      = doc["parameters"]["color"] | "";
  const char* state      = doc["parameters"]["state"] | "";
  int         brightness = doc["parameters"]["brightness"] | -1;

  // brightness > 0 counts as ON; brightness == 0 counts as OFF
  bool isOn = (brightness > 0) || (strcmp(state, "on") == 0);

  if (strcmp(color, "all") == 0 || strlen(color) == 0) {
    digitalWrite(RED_LED_PIN,   isOn ? HIGH : LOW);
    digitalWrite(GREEN_LED_PIN, isOn ? HIGH : LOW);
    digitalWrite(BLUE_LED_PIN,  isOn ? HIGH : LOW);
  } else {
    int pin = -1;
    if      (strcmp(color, "red")   == 0) pin = RED_LED_PIN;
    else if (strcmp(color, "green") == 0) pin = GREEN_LED_PIN;
    else if (strcmp(color, "blue")  == 0) pin = BLUE_LED_PIN;

    if (pin >= 0) {
      digitalWrite(pin, isOn ? HIGH : LOW);
    }
  }

  return sendText(req, "200 OK", "Command processed");
}

// ---------- setup / loop ----------

void startHttpsServer() {
  httpd_ssl_config_t conf = HTTPD_SSL_CONFIG_DEFAULT();
  conf.servercert     = (const uint8_t*)clank_cert_pem;
  conf.servercert_len = strlen(clank_cert_pem) + 1;   // mbedtls PEM needs the NUL
  conf.prvtkey_pem    = (const uint8_t*)clank_key_pem;
  conf.prvtkey_len    = strlen(clank_key_pem) + 1;
  conf.port_secure    = 443;
  conf.httpd.stack_size = 10240;  // TLS handshake needs a larger task stack

  esp_err_t ret = httpd_ssl_start(&server, &conf);
  if (ret != ESP_OK) {
    Serial.printf("HTTPS server failed to start (err 0x%x)\n", ret);
    return;
  }

  httpd_uri_t led_uri = {
    .uri = "/led-control", .method = HTTP_POST, .handler = handleLedControl, .user_ctx = NULL
  };
  httpd_register_uri_handler(server, &led_uri);

  httpd_uri_t health_uri = {
    .uri = "/health", .method = HTTP_GET, .handler = handleHealth, .user_ctx = NULL
  };
  httpd_register_uri_handler(server, &health_uri);

  Serial.println("HTTPS server started on port 443");
}

void setup() {
  Serial.begin(115200);

  pinMode(RED_LED_PIN,   OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(BLUE_LED_PIN,  OUTPUT);

  // All LEDs on at boot
  digitalWrite(RED_LED_PIN,   HIGH);
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(BLUE_LED_PIN,  HIGH);

  // Connect to WiFi using the fixed static IP (pinned by the certificate).
  if (!WiFi.config(local_IP, gateway_IP, subnet_mask, gateway_IP)) {
    Serial.println("Static IP configuration failed");
  }
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected to WiFi");
  Serial.println("IP address: " + WiFi.localIP().toString());

  // Start mDNS — advertises _clank-led._tcp on the TLS port. The "secure"
  // TXT record tells Clank's discovery to use https.
  if (MDNS.begin(MDNS_HOSTNAME)) {
    MDNS.addService("clank-led", "tcp", 443);
    MDNS.addServiceTxt("clank-led", "tcp", "secure", "true");
    Serial.println("mDNS started: " + String(MDNS_HOSTNAME) + ".local");
  } else {
    Serial.println("mDNS failed to start");
  }

  startHttpsServer();
}

void loop() {
  // The HTTPS server runs in its own FreeRTOS task; nothing to do here.
  delay(1000);
}
