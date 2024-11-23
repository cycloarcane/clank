#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WebServer.h>

// WiFi credentials
const char* ssid = "";
const char* password = "";

// LED pins - adjust based on your connections
const int RED_LED_PIN = 18;    // GPIO18
const int GREEN_LED_PIN = 23;  // GPIO23
const int BLUE_LED_PIN = 16;


WebServer server(80);

void setup() {
  Serial.begin(115200);
  
  // Configure LED pins as outputs
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(BLUE_LED_PIN, OUTPUT);


  // Turn all LEDs off initially
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(BLUE_LED_PIN, HIGH);


  // Connect to WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected to WiFi");
  Serial.println("IP address: " + WiFi.localIP().toString());

  // Setup HTTP endpoint to receive LED commands
  server.on("/led-control", HTTP_POST, handleLedControl);
  server.begin();
}

void loop() {
  server.handleClient();
}

void handleLedControl() {
  if (server.hasArg("plain")) {
    String json = server.arg("plain");
    StaticJsonDocument<200> doc;
    
    DeserializationError error = deserializeJson(doc, json);
    if (error) {
      server.send(400, "text/plain", "Invalid JSON");
      return;
    }

    // Process the command
    if (doc["action"] == "led_control") {
      const char* color = doc["parameters"]["color"] | "";
      const char* state = doc["parameters"]["state"] | "";
      int brightness = doc["parameters"]["brightness"] | -1;

      // For now, treat any brightness > 0 as ON, 0 as OFF
      bool isOn = (brightness > 0) || (strcmp(state, "on") == 0);

      // Handle all LEDs command
      if (strlen(color) == 0) {
        digitalWrite(RED_LED_PIN, isOn ? HIGH : LOW);
        digitalWrite(GREEN_LED_PIN, isOn ? HIGH : LOW);
        digitalWrite(BLUE_LED_PIN, isOn ? HIGH : LOW);
      } 
      // Handle individual LED commands
      else {
        int pin = -1;
        if (strcmp(color, "red") == 0) pin = RED_LED_PIN;
        else if (strcmp(color, "green") == 0) pin = GREEN_LED_PIN;
        else if (strcmp(color, "blue") == 0) pin = BLUE_LED_PIN;

        if (pin >= 0) {
          if (strcmp(state, "off") == 0) {
            digitalWrite(pin, LOW);
          } else if (strcmp(state, "on") == 0) {
            digitalWrite(pin, HIGH);
          }
        }
      }
      
      server.send(200, "text/plain", "Command processed");
    } else {
      server.send(400, "text/plain", "Unknown action");
    }
  } else {
    server.send(400, "text/plain", "No data received");
  }
}