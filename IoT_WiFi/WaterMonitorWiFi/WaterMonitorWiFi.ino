#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <GravityTDS.h>
#include <EEPROM.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_system.h>
#include <math.h>
#include "config.h"

constexpr int PH_PIN = 34, TDS_PIN = 35, TEMP_PIN = 18;
constexpr float V_PH401 = 1.9660f, V_PH686 = 1.4752f, V_PH918 = 1.0699f;
constexpr float DIVIDER_RATIO = 2.0f, ALPHA = 0.20f;
constexpr int SAMPLE_COUNT = 21;
// Match the standalone GravityTDS sketch if customized.
constexpr int TDS_K_ADDRESS = 8;
constexpr int EEPROM_BYTES = 64;

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
OneWire oneWire(TEMP_PIN);
DallasTemperature thermometer(&oneWire);
GravityTDS gravityTds;
DeviceAddress probe;
bool haveProbe = false, oledReady = false, tdsReady = false;
float filteredVoltage = NAN;
const char* tempStatus = "missing";
const char* tdsStatus = "starting";
String bootId;
uint32_t seq = 0;
unsigned long lastSend = 0, lastReconnect = 0;

String numberOrNull(float value, int decimals) {
  return isfinite(value) ? String(value, decimals) : String("null");
}

float medianPhVoltage() {
  float samples[SAMPLE_COUNT];
  for (int i = 0; i < SAMPLE_COUNT; ++i) {
    samples[i] = analogReadMilliVolts(PH_PIN) / 1000.0f;
    delay(15);
  }
  for (int i = 1; i < SAMPLE_COUNT; ++i) {
    float key = samples[i];
    int j = i;
    while (j > 0 && samples[j-1] > key) {
      samples[j] = samples[j-1];
      --j;
    }
    samples[j] = key;
  }
  return samples[SAMPLE_COUNT / 2];
}

float calculatePH(float voltage) {
  if (voltage >= V_PH686)
    return 6.86f + (voltage - V_PH686) * (4.01f - 6.86f) / (V_PH401 - V_PH686);
  return 6.86f + (voltage - V_PH686) * (9.18f - 6.86f) / (V_PH918 - V_PH686);
}

float readTemperature() {
  if (!haveProbe) {
    thermometer.begin();
    if (!thermometer.getAddress(probe, 0)) {
      tempStatus = "missing";
      return NAN;
    }
    if (probe[0] != 0x28) {
      tempStatus = "not_ds18b20";
      return NAN;
    }
    thermometer.setResolution(probe, 12);
    thermometer.setWaitForConversion(true);
    haveProbe = true;
  }
  thermometer.requestTemperatures();
  float t = thermometer.getTempC(probe);
  if (!isfinite(t) || t < -55 || t > 125 || t == DEVICE_DISCONNECTED_C) {
    haveProbe = false;
    tempStatus = "read_error";
    return NAN;
  }
  tempStatus = "ok";
  return t;
}

float readTds(float t) {
  if (!tdsReady) {
    tdsStatus = "storage_error";
    return NAN;
  }
  if (!isfinite(t) || t < 0 || t > 100) {
    tdsStatus = "no_temperature";
    return NAN;
  }
  gravityTds.setTemperature(t);
  gravityTds.update();
  if (!EEPROM.commit()) {
    tdsStatus = "storage_error";
    return NAN;
  }
  float ppm = gravityTds.getTdsValue();
  float k = gravityTds.getKvalue();
  if (!isfinite(ppm) || ppm < 0 || !isfinite(k) || k <= 0.25f || k >= 4.0f) {
    tdsStatus = "read_error";
    return NAN;
  }
  tdsStatus = "ok";
  return ppm;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  oledReady = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C, true, false);
  if (oledReady) {
    oled.clearDisplay();
    oled.setTextColor(SSD1306_WHITE);
    oled.setTextSize(1);
    oled.display();
  }
  analogReadResolution(12);
  analogSetPinAttenuation(PH_PIN, ADC_11db);
  analogSetPinAttenuation(TDS_PIN, ADC_11db);
  tdsReady = EEPROM.begin(EEPROM_BYTES);
  if (tdsReady) {
    gravityTds.setPin(TDS_PIN);
    gravityTds.begin();
  }
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  char id[17];
  snprintf(id, sizeof(id), "%08lx%08lx",
           (unsigned long)esp_random(), (unsigned long)esp_random());
  bootId = id;
}

String displayValue(float v, int digits) {
  return isfinite(v) ? String(v, digits) : String("--");
}

void loop() {
  float adc = medianPhVoltage();
  unsigned long phTime = millis();
  float raw = adc * DIVIDER_RATIO;
  Serial.printf("ADC: %.4f V | PO: %.4f V | pH: %.2f\n",
              adc, raw, calculatePH(raw));
  float ph = NAN;
  const char* phStatus = "invalid_reading";
  if (adc > 0 && adc < 3.1f) {
    float next = isfinite(filteredVoltage)
        ? ALPHA * raw + (1 - ALPHA) * filteredVoltage : raw;
    float candidate = calculatePH(next);
    if (isfinite(candidate) && candidate >= 0 && candidate <= 14 &&
        calculatePH(raw) >= 0 && calculatePH(raw) <= 14) {
      filteredVoltage = next;
      ph = candidate;
      phStatus = (next < V_PH918 || next > V_PH401)
          ? "outside_calibration" : "ok";
    }
  }
  if (!isfinite(ph)) filteredVoltage = NAN;
  float t = readTemperature();
  unsigned long tempTime = millis();
  float ppm = readTds(t);
  if (oledReady) {
    oled.clearDisplay();
    oled.setCursor(0, 0);
    oled.println(String("pH   ") + displayValue(ph, 2));
    oled.println(String("Temp ") + displayValue(t, 2) + " C");
    oled.println(String("TDS  ") + displayValue(ppm, 0) + " ppm");
    oled.display();
  }
  unsigned long now = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastReconnect >= 15000) {
      lastReconnect = now;
      WiFi.reconnect();
    }
    return;
  }
  if (now - lastSend < 5000) return;
  lastSend = now;
  String body;
  body.reserve(420);
  body = "{\"device_id\":\"" + WiFi.macAddress() + "\",\"boot_id\":\"" + bootId + "\"";
  body += ",\"seq\":" + String(seq++);
  body += ",\"context\":\"" + String(MEASUREMENT_CONTEXT) + "\"";
  body += ",\"ph_uptime_ms\":" + String(phTime);
  body += ",\"temperature_uptime_ms\":" + String(tempTime);
  body += ",\"adc_voltage_v\":" + numberOrNull(adc, 4);
  body += ",\"po_raw_v\":" + numberOrNull(raw, 4);
  body += ",\"po_filtered_v\":" + numberOrNull(filteredVoltage, 4);
  body += ",\"ph\":" + numberOrNull(ph, 3);
  body += ",\"ph_status\":\"" + String(phStatus) + "\"";
  body += ",\"temperature_c\":" + numberOrNull(t, 3);
  body += ",\"temperature_status\":\"" + String(tempStatus) + "\"";
  body += ",\"tds_ppm\":" + numberOrNull(ppm, 2);
  body += ",\"tds_status\":\"" + String(tdsStatus) + "\"}";

  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(1500);
  if (http.begin(SERVER_URL)) {
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", API_KEY);
    Serial.printf("HTTP %d\n", http.POST(body));
    http.end();
  }
}