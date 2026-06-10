// Clank RGB LED-strip controller — MQTT firmware.
//
// Drives a common-cathode RGB strip through three NPN transistors (GPIO -> base,
// strip channel -> collector, emitter -> GND). Each colour channel is dimmed
// with an 8-bit LEDC PWM signal, so wiring is ACTIVE-HIGH: duty 0 = off,
// duty 255 = full brightness.
//
// Control is entirely over MQTT (no HTTP server on the device):
//   subscribe  clank/rgb/set          <- JSON command (see below)
//   publish    clank/rgb/state        -> JSON current state (retained)
//   publish    clank/rgb/availability -> "online" / "offline" (retained, LWT)
//
// Command JSON (all fields optional):
//   {"state":"ON"|"OFF", "r":0-255, "g":0-255, "b":0-255, "brightness":0-255}
//   - sending any of r/g/b implies the strip turns ON (unless state is "OFF")
//   - brightness is a master scale applied to all three channels
//
// Libraries (install once):
//   arduino-cli lib install PubSubClient ArduinoJson

#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// WiFi creds, broker address + credentials. Copy secrets.h.example to secrets.h
// and fill in. secrets.h is gitignored so nothing sensitive is committed.
#include "secrets.h"

// baud 115200

// ---- RGB channel -> GPIO mapping (NPN transistor bases) ----
// Active-high: the strip is common-cathode and each channel is switched to GND
// by an NPN, so a higher PWM duty = brighter.
const int PIN_R = 13;
const int PIN_G = 33;
const int PIN_B = 14;

// LEDC PWM: 5 kHz is well above visible flicker and easy on the transistors;
// 8-bit resolution gives a 0-255 duty that maps 1:1 to colour values.
const int PWM_FREQ = 5000;
const int PWM_RES  = 8;

// mDNS hostname — device reachable at clank-rgb.local for debugging.
const char* MDNS_HOSTNAME = "clank-rgb";

// ---- MQTT topics ----
const char* TOPIC_SET     = "clank/rgb/set";
const char* TOPIC_STATE   = "clank/rgb/state";
const char* TOPIC_AVAIL   = "clank/rgb/availability";

WiFiClient   net;
PubSubClient mqtt(net);

// ---- current strip state ----
uint8_t curR = 255, curG = 255, curB = 255;  // colour (defaults to white)
uint8_t brightness = 255;                      // master scale 0-255
bool    isOn = false;                          // start OFF (nothing lit at boot)

char clientId[32];

// Scale an 8-bit channel by the master brightness (rounded).
uint8_t scaled(uint8_t channel) {
  return (uint16_t)channel * brightness / 255;
}

// Push the current logical state to the PWM outputs.
void applyOutput() {
  if (isOn) {
    ledcWrite(PIN_R, scaled(curR));
    ledcWrite(PIN_G, scaled(curG));
    ledcWrite(PIN_B, scaled(curB));
  } else {
    ledcWrite(PIN_R, 0);
    ledcWrite(PIN_G, 0);
    ledcWrite(PIN_B, 0);
  }
}

// Print current state to the serial monitor (mirrors the old relay firmware).
void printStatus() {
  Serial.println(F("---- RGB status ----"));
  Serial.printf("  power     : %s\n", isOn ? "ON" : "OFF");
  Serial.printf("  colour    : R=%-3u G=%-3u B=%-3u\n", curR, curG, curB);
  Serial.printf("  brightness: %u\n", brightness);
  Serial.println(F("--------------------"));
}

// Publish the current state as retained JSON so a late subscriber (or Clank
// restart) immediately learns the strip's colour without prompting it.
void publishState() {
  JsonDocument doc;
  doc["state"]      = isOn ? "ON" : "OFF";
  doc["r"]          = curR;
  doc["g"]          = curG;
  doc["b"]          = curB;
  doc["brightness"] = brightness;
  char buf[96];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  mqtt.publish(TOPIC_STATE, (const uint8_t*)buf, n, true);  // retained
}

// Clamp a JSON number to 0-255.
uint8_t clamp8(int v) {
  if (v < 0)   return 0;
  if (v > 255) return 255;
  return (uint8_t)v;
}

// ---- MQTT message handler ----
void onMessage(char* topic, byte* payload, unsigned int length) {
  if (length == 0 || length > 200) return;  // commands are tiny

  char buf[201];
  memcpy(buf, payload, length);
  buf[length] = '\0';
  Serial.printf("RX %s: %s\n", topic, buf);

  JsonDocument doc;
  if (deserializeJson(doc, buf, length)) {
    Serial.println(F("  -> rejected: invalid JSON"));
    return;
  }

  bool colourGiven = doc["r"].is<int>() || doc["g"].is<int>() || doc["b"].is<int>();
  bool brightGiven = doc["brightness"].is<int>();
  if (doc["r"].is<int>()) curR = clamp8(doc["r"].as<int>());
  if (doc["g"].is<int>()) curG = clamp8(doc["g"].as<int>());
  if (doc["b"].is<int>()) curB = clamp8(doc["b"].as<int>());
  if (brightGiven) brightness = clamp8(doc["brightness"].as<int>());

  // Explicit state wins; otherwise setting a colour or brightness implies ON.
  if (doc["state"].is<const char*>()) {
    const char* s = doc["state"];
    isOn = (strcasecmp(s, "on") == 0);
  } else if (colourGiven || brightGiven) {
    isOn = true;
  }

  applyOutput();
  printStatus();
  publishState();
}

// ---- connectivity ----
void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.println("WiFi connected, IP: " + WiFi.localIP().toString());

  // Disable modem-sleep so incoming MQTT messages aren't delayed by the radio
  // powering down between beacons; reconnect automatically after AP drops.
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);

  if (MDNS.begin(MDNS_HOSTNAME)) {
    Serial.println("mDNS started: " + String(MDNS_HOSTNAME) + ".local");
  }
}

// (Re)connect to the broker. Registers a Last-Will so the broker marks the
// device "offline" if it drops without a clean disconnect.
void connectMqtt() {
  while (!mqtt.connected()) {
    Serial.print("Connecting to MQTT broker " MQTT_BROKER " ... ");
    bool ok = mqtt.connect(
        clientId, MQTT_USER, MQTT_PASS,
        TOPIC_AVAIL, 0, true, "offline");  // LWT: retained "offline"
    if (ok) {
      Serial.println("connected");
      mqtt.publish(TOPIC_AVAIL, "online", true);  // retained
      mqtt.subscribe(TOPIC_SET);
      publishState();
    } else {
      Serial.printf("failed (rc=%d), retrying in 2s\n", mqtt.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);

  // Attach PWM to each channel and start with everything off so the strip is
  // dark through boot/reset.
  ledcAttach(PIN_R, PWM_FREQ, PWM_RES);
  ledcAttach(PIN_G, PWM_FREQ, PWM_RES);
  ledcAttach(PIN_B, PWM_FREQ, PWM_RES);
  applyOutput();
  Serial.println(F("\nBoot: RGB outputs initialised OFF"));
  printStatus();

  // Unique client id from the MAC so two devices never collide on the broker.
  uint64_t mac = ESP.getEfuseMac();
  snprintf(clientId, sizeof(clientId), "clank-rgb-%04X", (uint16_t)(mac >> 32));

  connectWifi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMessage);
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();
}
