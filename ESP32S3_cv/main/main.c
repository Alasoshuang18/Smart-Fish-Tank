#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#define WIFI_SSID "iPhoneAlaso"
#define WIFI_PASS "3342880042lh"
#define LED_GPIO 2
#define CAM_XCLK -1
#define CAM_SDA 39
#define CAM_SCL 38
#define CAM_D7 18
#define CAM_D6 17
#define CAM_D5 16
#define CAM_D4 15
#define CAM_D3 7
#define CAM_D2 6
#define CAM_D1 5
#define CAM_D0 4
#define CAM_VSYNC 47
#define CAM_HREF 48
#define CAM_PCLK 45
// OV2640 白平衡预设：1 sunny, 2 cloudy, 3 office, 4 home。白光偏绿时先试 office。
#define OV2640_WB_MODE 1
static const char *TAG = "camera";
static i2c_master_dev_handle_t xl_dev;
static void xl_write(uint8_t reg, uint8_t val)
{
  uint8_t b[2] = {reg, val};
  ESP_ERROR_CHECK(i2c_master_transmit(xl_dev, b, 2, 100));
}
static void xl9555_init(void)
{
  i2c_master_bus_handle_t bus;
  i2c_master_bus_config_t bc = {.i2c_port = I2C_NUM_0, .sda_io_num = 41, .scl_io_num = 42, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7, .flags.enable_internal_pullup = true};
  ESP_ERROR_CHECK(i2c_new_master_bus(&bc, &bus));
  i2c_device_config_t dc = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = 0x20, .scl_speed_hz = 400000};
  ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dc, &xl_dev));
  xl_write(0x06, 0xCF);
  xl_write(0x07, 0xFF);
}
static void xl9555_camera_enable(void)
{
  xl_write(0x02, 0x00);
  vTaskDelay(pdMS_TO_TICKS(20));
  xl_write(0x02, 0x20);
  vTaskDelay(pdMS_TO_TICKS(20));
}
static esp_err_t camera_init(void)
{
  camera_config_t c = {.pin_pwdn = -1, .pin_reset = -1, .pin_xclk = CAM_XCLK, .pin_sccb_sda = CAM_SDA, .pin_sccb_scl = CAM_SCL, .pin_d7 = CAM_D7, .pin_d6 = CAM_D6, .pin_d5 = CAM_D5, .pin_d4 = CAM_D4, .pin_d3 = CAM_D3, .pin_d2 = CAM_D2, .pin_d1 = CAM_D1, .pin_d0 = CAM_D0, .pin_vsync = CAM_VSYNC, .pin_href = CAM_HREF, .pin_pclk = CAM_PCLK, .xclk_freq_hz = 20000000, .ledc_timer = LEDC_TIMER_0, .ledc_channel = LEDC_CHANNEL_0, .pixel_format = PIXFORMAT_JPEG, .frame_size = FRAMESIZE_VGA, .jpeg_quality = 12, .fb_count = 2, .fb_location = CAMERA_FB_IN_PSRAM, .grab_mode = CAMERA_GRAB_LATEST};
  return esp_camera_init(&c);
}
static esp_err_t camera_settle_and_lock(void)
{
  sensor_t *sensor = esp_camera_sensor_get();
  if (!sensor)
    return ESP_FAIL;

  /* Let automatic exposure, gain and white balance converge first. */
  if (sensor->set_exposure_ctrl)
    sensor->set_exposure_ctrl(sensor, 1);
  if (sensor->set_gain_ctrl)
    sensor->set_gain_ctrl(sensor, 1);
  if (sensor->set_whitebal)
    sensor->set_whitebal(sensor, 1);
  if (sensor->set_awb_gain)
    sensor->set_awb_gain(sensor, 1);
  for (int i = 0; i < 8; ++i)
  {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb)
      esp_camera_fb_return(fb);
    vTaskDelay(pdMS_TO_TICKS(100));
  }

  /* Freeze the converged values for stable color comparisons. */
  if (sensor->set_exposure_ctrl)
    sensor->set_exposure_ctrl(sensor, 0);
  if (sensor->set_gain_ctrl)
    sensor->set_gain_ctrl(sensor, 0);
  /* Keep AWB enabled so the sensor continuously compensates the LED color. */
  if (sensor->set_whitebal)
    sensor->set_whitebal(sensor, 1);
  if (sensor->set_awb_gain)
    sensor->set_awb_gain(sensor, 1);
  if (sensor->set_wb_mode)
    sensor->set_wb_mode(sensor, 0);
  if (sensor->set_saturation)

    sensor->set_saturation(sensor, 0);
  if (sensor->set_contrast)
    sensor->set_contrast(sensor, 0);
  ESP_LOGI(TAG, "camera controls settled: exposure locked, continuous AWB enabled");
  return ESP_OK;
}

static int cfg_roi_x = 0, cfg_roi_y = 0, cfg_roi_w = 40, cfg_roi_h = 40;
static float cfg_threshold = 6.0f;
static int cfg_ae_level = 0;

static esp_err_t api_config(httpd_req_t *r)
{
  char body[256];
  int len = r->content_len;
  if (len <= 0 || len >= (int)sizeof(body))
    return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "invalid config size");
  int got = httpd_req_recv(r, body, len);
  if (got <= 0)
    return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "config body missing");
  body[got] = '\0';
  int parsed = sscanf(body, "{\"roi_x\":%d,\"roi_y\":%d,\"roi_w\":%d,\"roi_h\":%d,\"threshold\":%f}", &cfg_roi_x, &cfg_roi_y, &cfg_roi_w, &cfg_roi_h, &cfg_threshold);
  char *ae = strstr(body, "\"ae_level\"");
  if (ae) sscanf(ae, "\"ae_level\":%d", &cfg_ae_level);
  if (cfg_ae_level < -3) cfg_ae_level = -3;
  if (cfg_ae_level > 3) cfg_ae_level = 3;
  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor && sensor->set_ae_level) sensor->set_ae_level(sensor, cfg_ae_level);
  if (parsed < 2 && !ae)
    return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "invalid config JSON");
  if (cfg_roi_w < 1)
    cfg_roi_w = 1;
  if (cfg_roi_h < 1)
    cfg_roi_h = 1;
  httpd_resp_set_type(r, "application/json");
  char response[256];
  int n = snprintf(response, sizeof(response), "{\"ok\":true,\"roi_x\":%d,\"roi_y\":%d,\"roi_w\":%d,\"roi_h\":%d,\"threshold\":%.2f}", cfg_roi_x, cfg_roi_y, cfg_roi_w, cfg_roi_h, cfg_threshold);
  return httpd_resp_send(r, response, n);
}

static esp_err_t capture(httpd_req_t *r)
{
  camera_fb_t *f = esp_camera_fb_get();
  if (!f)
  {
    ESP_LOGE(TAG, "capture failed: camera returned no frame");
    return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "camera capture failed");
  }
  ESP_LOGI(TAG, "capture frame: %u bytes", (unsigned)f->len);
  httpd_resp_set_type(r, "image/jpeg");
  httpd_resp_set_hdr(r, "Cache-Control", "no-store, no-cache, must-revalidate");
  esp_err_t e = httpd_resp_send(r, (char *)f->buf, f->len);
  esp_camera_fb_return(f);
  return e;
}
static esp_err_t stream(httpd_req_t *r)
{
  ESP_LOGI(TAG, "stream request received");
  httpd_resp_set_status(r, "200 OK");
  httpd_resp_set_type(r, "multipart/x-mixed-replace; boundary=frame");
  httpd_resp_set_hdr(r, "Cache-Control", "no-store, no-cache, must-revalidate");
  while (1)
  {
    camera_fb_t *f = esp_camera_fb_get();
    if (!f)
      break;
    char h[80];
    int l = snprintf(h, sizeof(h), "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", (unsigned)f->len);
    esp_err_t eh = httpd_resp_send_chunk(r, h, l);
    esp_err_t ed = eh == ESP_OK ? httpd_resp_send_chunk(r, (char *)f->buf, f->len) : eh;
    if (eh != ESP_OK || ed != ESP_OK)
    {
      ESP_LOGW(TAG, "stream client disconnected: header=%s data=%s", esp_err_to_name(eh), esp_err_to_name(ed));
      esp_camera_fb_return(f);
      break;
    }
    esp_camera_fb_return(f);
    esp_err_t et = httpd_resp_send_chunk(r, "\r\n", 2);
    if (et != ESP_OK)
    {
      ESP_LOGW(TAG, "stream trailer failed: %s", esp_err_to_name(et));
      break;
    }
    vTaskDelay(pdMS_TO_TICKS(33));
  }
  httpd_resp_send_chunk(r, NULL, 0);
  return ESP_OK;
}
static void wifi_init(void)
{
  esp_err_t ne = nvs_flash_init_partition("nvs");
  if (ne == ESP_ERR_NVS_NO_FREE_PAGES || ne == ESP_ERR_NVS_NEW_VERSION_FOUND || ne == ESP_ERR_NVS_NOT_FOUND)
  {
    esp_err_t ee = nvs_flash_erase_partition("nvs");
    if (ee != ESP_OK && ee != ESP_ERR_NVS_NOT_FOUND)
      ESP_LOGW(TAG, "NVS erase: %s", esp_err_to_name(ee));
    ne = nvs_flash_init_partition("nvs");
  }
  if (ne != ESP_OK)
    ESP_LOGW(TAG, "NVS init: %s, continue with SoftAP", esp_err_to_name(ne));
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_ap();
  wifi_init_config_t c = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&c));
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
  wifi_config_t ap = {.ap = {.ssid = "ESP32-CAM", .ssid_len = 9, .password = "12345678", .channel = 1, .max_connection = 4, .authmode = WIFI_AUTH_WPA_WPA2_PSK}};
  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
  ESP_ERROR_CHECK(esp_wifi_start());
  ESP_LOGI(TAG, "AP ready: http://192.168.4.1/stream");
}
void app_main(void)
{
  gpio_set_direction(LED_GPIO, GPIO_MODE_OUTPUT);
  gpio_set_level(LED_GPIO, 1);
  vTaskDelay(pdMS_TO_TICKS(1000));
  xl9555_init();
  xl9555_camera_enable();
  esp_err_t cam_err = camera_init();
  if (cam_err != ESP_OK)
    ESP_LOGE(TAG, "camera init failed: %s", esp_err_to_name(cam_err));
  else if (camera_settle_and_lock() != ESP_OK)
    ESP_LOGW(TAG, "camera control lock failed; continuing with sensor defaults");
  wifi_init();
  vTaskDelay(pdMS_TO_TICKS(5000));
  esp_netif_ip_info_t ip;
  esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
  esp_netif_get_ip_info(netif, &ip);
  ESP_LOGI(TAG, "ESP32 IP: " IPSTR, IP2STR(&ip.ip));
  httpd_handle_t h;
  httpd_config_t c = HTTPD_DEFAULT_CONFIG();
  httpd_start(&h, &c);
  httpd_uri_t u = {.uri = "/capture.jpg", .method = HTTP_GET, .handler = capture};
  httpd_register_uri_handler(h, &u);
  httpd_uri_t cfg = {.uri = "/api/config", .method = HTTP_POST, .handler = api_config};
  httpd_register_uri_handler(h, &cfg);
  httpd_uri_t v = {.uri = "/stream", .method = HTTP_GET, .handler = stream};
  httpd_register_uri_handler(h, &v);
  ESP_LOGI(TAG, "GET /capture.jpg");
  while (1)
    vTaskDelay(pdMS_TO_TICKS(1000));
}
