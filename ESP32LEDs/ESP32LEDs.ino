#include <WiFi.h>
#include <ArduinoJson.h>
#include <WebServer.h>
#include <ESPmDNS.h>

// baud 115200

// WiFi credentials — set before flashing, or use a provisioning method
const char* ssid = "";
const char* password = "";

// mDNS hostname — device will be reachable at clank-led.local
const char* MDNS_HOSTNAME = "clank-led";

// LED pins — adjust based on your wiring
const int RED_LED_PIN   = 18;  // GPIO18
const int GREEN_LED_PIN = 23;  // GPIO23
const int BLUE_LED_PIN  = 16;  // GPIO16

WebServer server(80);

// ---------- handlers ----------

void handleHealth() {
  // Clank discovery service checks GET /health for {"service":"clank-led"}
  server.send(200, "application/json", "{\"service\":\"clank-led\",\"status\":\"ok\"}");
}

void handleLedControl() {
  if (!server.hasArg("plain")) {
    server.send(400, "text/plain", "No data received");
    return;
  }

  String json = server.arg("plain");
  StaticJsonDocument<200> doc;

  DeserializationError error = deserializeJson(doc, json);
  if (error) {
    server.send(400, "text/plain", "Invalid JSON");
    return;
  }

  if (doc["action"] != "led_control") {
    server.send(400, "text/plain", "Unknown action");
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

  server.send(200, "text/plain", "Command processed");
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

  // Start mDNS — advertises _clank-led._tcp so Python discovery finds us
  if (MDNS.begin(MDNS_HOSTNAME)) {
    MDNS.addService("clank-led", "tcp", 80);
    Serial.println("mDNS started: " + String(MDNS_HOSTNAME) + ".local");
  } else {
    Serial.println("mDNS failed to start");
  }

  server.on("/health",      HTTP_GET,  handleHealth);
  server.on("/led-control", HTTP_POST, handleLedControl);
  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  server.handleClient();
}
