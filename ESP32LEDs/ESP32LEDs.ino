#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoJson.h>

// HTTPS server — install "esp32_https_server" by Frank Hessel via the
// Arduino Library Manager (Sketch -> Include Library -> Manage Libraries).
#include <HTTPSServer.hpp>
#include <SSLCert.hpp>
#include <HTTPRequest.hpp>
#include <HTTPResponse.hpp>

// TLS certificate + private key, as DER byte arrays.
// Generate before flashing:  python3 scripts/generate_esp32_cert.py --ip <device-ip>
// cert.h contains the private key and must never be committed (see .gitignore).
#include "cert.h"

using namespace httpsserver;

// baud 115200

// WiFi credentials — set before flashing, or use a provisioning method
const char* ssid     = "";
const char* password = "";

// Shared API key — must match ESP32_API_KEY env var on the Python side.
// Generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
// Leave empty ("") to disable authentication (not recommended).
const char* API_KEY = "";

// mDNS hostname — device will be reachable at clank-led.local
const char* MDNS_HOSTNAME = "clank-led";

// LED pins — adjust based on your wiring
const int RED_LED_PIN   = 18;  // GPIO18
const int GREEN_LED_PIN = 23;  // GPIO23
const int BLUE_LED_PIN  = 16;  // GPIO16

// HTTPS on the standard TLS port. The cert/key come from cert.h.
SSLCert    cert((unsigned char*)clank_cert_der, clank_cert_der_len,
                (unsigned char*)clank_key_der,  clank_key_der_len);
HTTPSServer secureServer(&cert, 443);

// ---------- rate limiting ----------
// Sliding-window limiter: at most RATE_LIMIT_MAX requests per
// RATE_LIMIT_WINDOW_MS. Applied to /led-control before authentication so
// it also throttles API-key brute-force attempts. The server handles one
// client at a time, so a single global window is sufficient.
const int           RATE_LIMIT_MAX       = 60;       // requests per window
const unsigned long RATE_LIMIT_WINDOW_MS = 60000UL;  // 60 seconds

unsigned long requestTimes[RATE_LIMIT_MAX];
int           requestCount = 0;

// Returns true if a new request is allowed, recording it if so.
// Unsigned subtraction makes this correct across millis() overflow (~49 days).
bool rateLimitAllow() {
  unsigned long now = millis();

  // Drop timestamps that have aged out of the window (compact in place).
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
bool isAuthenticated(HTTPRequest* req) {
  if (strlen(API_KEY) == 0) return true;

  std::string provided = req->getHeader("X-API-Key");
  size_t keyLen = strlen(API_KEY);

  // Constant-time compare: always scan the full key length and fold any
  // length mismatch into the result so timing does not reveal the key.
  unsigned char diff = (unsigned char)(provided.length() ^ keyLen);
  for (size_t i = 0; i < keyLen; i++) {
    char p = (i < provided.length()) ? provided[i] : 0;
    diff |= (unsigned char)(p ^ API_KEY[i]);
  }
  return diff == 0;
}

void sendText(HTTPResponse* res, int code, const char* status, const char* body) {
  res->setStatusCode(code);
  res->setStatusText(status);
  res->setHeader("Content-Type", "text/plain");
  res->print(body);
}

// ---------- handlers ----------

void handleHealth(HTTPRequest* req, HTTPResponse* res) {
  // Public endpoint — no auth required.
  // Clank discovery service checks GET /health for {"service":"clank-led"}.
  res->setStatusCode(200);
  res->setHeader("Content-Type", "application/json");
  res->print("{\"service\":\"clank-led\",\"status\":\"ok\"}");
}

void handleLedControl(HTTPRequest* req, HTTPResponse* res) {
  if (!rateLimitAllow()) {
    sendText(res, 429, "Too Many Requests", "Rate limit exceeded");
    return;
  }

  if (!isAuthenticated(req)) {
    sendText(res, 401, "Unauthorized", "Authentication failed");
    return;
  }

  // Read the request body (bounded — the command JSON is tiny).
  byte   buffer[256];
  size_t idx = 0;
  while (!req->requestComplete() && idx < sizeof(buffer)) {
    idx += req->readBytes(buffer + idx, sizeof(buffer) - idx);
  }
  req->discardRequestBody();

  if (idx == 0) {
    sendText(res, 400, "Bad Request", "No data received");
    return;
  }

  StaticJsonDocument<200> doc;
  DeserializationError error = deserializeJson(doc, buffer, idx);
  if (error) {
    sendText(res, 400, "Bad Request", "Invalid JSON");
    return;
  }

  if (doc["action"] != "led_control") {
    sendText(res, 400, "Bad Request", "Unknown action");
    return;
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

  sendText(res, 200, "OK", "Command processed");
}

// ---------- setup / loop ----------

void setup() {
  Serial.begin(115200);

  pinMode(RED_LED_PIN,   OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(BLUE_LED_PIN,  OUTPUT);

  // All LEDs on at boot
  digitalWrite(RED_LED_PIN,   HIGH);
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(BLUE_LED_PIN,  HIGH);

  // Connect to WiFi
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

  // Register routes and start the HTTPS server.
  secureServer.registerNode(new ResourceNode("/health",      "GET",  &handleHealth));
  secureServer.registerNode(new ResourceNode("/led-control", "POST", &handleLedControl));
  secureServer.start();

  if (secureServer.isRunning()) {
    Serial.println("HTTPS server started on port 443");
  } else {
    Serial.println("HTTPS server failed to start");
  }
}

void loop() {
  secureServer.loop();
}
