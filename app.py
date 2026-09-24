import datetime
import json
import os
import re
from cachetools import TTLCache, cached
from flask import Flask, redirect, render_template, request, url_for
from google import genai
from google.genai import types
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

MODEL_NAME = "gemini-3.1-flash-lite"
BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# Cache tối đa 100 phần tử, TTL 24 giờ
weather_cache = TTLCache(maxsize=100, ttl=86400)
pdf_cache = TTLCache(maxsize=10, ttl=86400)
ai_cache = TTLCache(maxsize=10, ttl=86400)


def get_data_version(now_vn):
  """Sinh phiên bản dữ liệu: Tự động đổi version đúng lúc 11:00 AM hàng ngày."""
  today_str = now_vn.strftime("%Y-%m-%d")
  version = "v1_morning" if now_vn.hour < 11 else "v2_post11am"
  return f"{today_str}_{version}"


def get_three_workdays(from_date):
  workdays = []
  current = from_date
  while len(workdays) < 3:
    if current.weekday() < 5:
      workdays.append(current)
    current += datetime.timedelta(days=1)
  return workdays


@cached(weather_cache)
def fetch_hourly_weather_thao_dien(target_date_str, data_ver):
  api_key = os.getenv("WEATHER_API_KEY", "")

  # Nếu chưa cài WEATHER_API_KEY -> Tự động dùng Met.no làm dự phòng (Không cần Key)
  if not api_key:
    return fetch_from_met_no(target_date_str)

  url = f"http://api.weatherapi.com/v1/forecast.json?key={api_key}&q=10.8031,106.7324&dt={target_date_str}"
  print(f"\n[WEATHER LOG] Fetching WeatherAPI.com for {target_date_str}")

  try:
    res = requests.get(url, timeout=5)
    if res.status_code == 200:
      data = res.json()
      forecast_days = data.get("forecast", {}).get("forecastday", [])

      if forecast_days:
        hours = forecast_days[0].get("hour", [])

        # Lọc giờ đi làm (7h, 8h, 9h)
        morning_hours = [
            h for h in hours if 7 <= int(h["time"].split()[1].split(":")[0]) <= 9
        ]
        # Lọc giờ tan tầm (17h, 18h, 19h)
        evening_hours = [
            h
            for h in hours
            if 17 <= int(h["time"].split()[1].split(":")[0]) <= 19
        ]

        morning_rain = round(
            sum(h.get("precip_mm", 0.0) for h in morning_hours), 1
        )
        morning_prob = max(
            [h.get("chance_of_rain", 0) for h in morning_hours] or [0]
        )

        evening_rain = round(
            sum(h.get("precip_mm", 0.0) for h in evening_hours), 1
        )
        evening_prob = max(
            [h.get("chance_of_rain", 0) for h in evening_hours] or [0]
        )

        result = {
            "morning_rain": morning_rain,
            "morning_prob": morning_prob,
            "evening_rain": evening_rain,
            "evening_prob": evening_prob,
        }
        print(f"[WEATHER LOG] WeatherAPI Result: {result}")
        return result

  except Exception as e:
    print(f"[WEATHER LOG ERROR] WeatherAPI failed: {e}")

  return fetch_from_met_no(target_date_str)


# Hàm dự phòng dùng Met.no (Miễn phí 100%, không cần API Key, không lo cấm IP)
def fetch_from_met_no(target_date_str):
  url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=10.8031&lon=106.7324"
  headers = {"User-Agent": "ThaoDienTVDashboard/1.0 (contact@banqup.vn)"}
  try:
    res = requests.get(url, headers=headers, timeout=5)
    if res.status_code == 200:
      timeseries = (
          res.json().get("properties", {}).get("timeseries", [])
      )
      m_rain, e_rain = 0.0, 0.0

      for item in timeseries:
        t_utc = datetime.datetime.strptime(
            item["time"], "%Y-%m-%dT%H:%M:%SZ"
        )
        t_vn = t_utc + datetime.timedelta(hours=7)

        if t_vn.strftime("%Y-%m-%d") == target_date_str:
          precip = (
              item.get("data", {})
              .get("next_1_hours", {})
              .get("details", {})
              .get("precipitation_amount", 0.0)
          )
          if 7 <= t_vn.hour <= 9:
            m_rain += precip
          elif 17 <= t_vn.hour <= 19:
            e_rain += precip

      m_rain = round(m_rain, 1)
      e_rain = round(e_rain, 1)

      return {
          "morning_rain": m_rain,
          "morning_prob": 80 if m_rain > 0.5 else (40 if m_rain > 0 else 10),
          "evening_rain": e_rain,
          "evening_prob": 85 if e_rain > 0.5 else (40 if e_rain > 0 else 10),
      }
  except Exception as e:
    print(f"[WEATHER LOG ERROR] Met.no failed: {e}")

  return {
      "morning_rain": 0.0,
      "morning_prob": 0,
      "evening_rain": 0.0,
      "evening_prob": 0,
  }

@cached(pdf_cache)
def fetch_latest_pdf(today_date_str, data_ver):
  today_date = datetime.datetime.strptime(today_date_str, "%Y-%m-%d").date()
  for i in range(5):
    check_date = today_date - datetime.timedelta(days=i)
    pdf_url = f"{BASE_DOMAIN}/phocadownload/{check_date.strftime('%Y')}/{check_date.strftime('%m-%Y')}/HCMC_TVHN_{check_date.strftime('%Y%m%d')}.pdf"
    try:
      res = requests.get(pdf_url, headers=HEADERS, timeout=2, verify=False)
      if res.status_code == 200 and len(res.content) > 1000:
        return check_date.strftime("%d/%m/%Y"), res.content
    except Exception:
      continue
  return None, None


@cached(ai_cache)
def analyze_three_workdays(pdf_date_str, dates_info_json, pdf_bytes, data_ver):
  fallback = [
      {
          "ngay": "N/A",
          "label": "HÔM NAY",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "17h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết ổn định.",
      },
      {
          "ngay": "N/A",
          "label": "NGÀY LÀM VIỆC TIẾP THEO 1",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "18h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết ổn định.",
      },
      {
          "ngay": "N/A",
          "label": "NGÀY LÀM VIỆC TIẾP THEO 2",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "19h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết ổn định.",
      },
  ]
  if not pdf_bytes or not GEMINI_API_KEY:
    return fallback
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
        Bạn là chuyên gia Phân tích Rủi ro Giao thông & Cảnh báo Ngập lụt nghiêm ngặt cho khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM) thuộc công ty Banqup VN.
        Tệp PDF thủy văn phát hành ngày: {pdf_date_str}.
        Dữ liệu thời tiết 3 ngày làm việc (Mưa & Xác suất mưa ca sáng 7h-9h và ca chiều 17h-19h): {dates_info_json}

        ========================================================================
        ĐẶC THÙ ĐỊA HÌNH & NGUYÊN TẮC AN TOÀN BẮT BUỘC TẠI THẢO ĐIỀN:
        1. ĐỊA HÌNH LÒNG CHẢO: Thảo Điền (Quốc Hương, Xuân Thủy, Nguyễn Văn Hưởng, Đỗ Quang) nằm ở cao độ thấp (0.5m - 1.2m), bao bọc 3 mặt bởi sông Sài Gòn.
        2. TÁC ĐỘNG KÉP: Chỉ cần Mưa rào bộc phát ngắn (>15mm) HOẶC Triều Phú An dâng >= 1.40m là các cống xả bị khóa ngược, gây ngập nhanh 20-50cm, chết máy và tê liệt giao thông ca đi làm/về.
        3. QUY TẮC NGUYÊN TẮC AN TOÀN TỐI ĐA (STRICT SAFETY BASELINE): Thà cảnh báo nhầm (Over-warn) còn hơn để nhân viên kẹt xe / chết máy trong vùng ngập.

        ========================================================================
        QUY TẮC ĐÁNH GIÁ VÀ PHÂN LOẠI TRẠNG THÁI WFH BẮT BUỘC (ĐỌC KỸ):

        🔴 TRẠNG THÁI 1: DANGER -> "NÊN LÀM VIỆC TẠI NHÀ (WFH)"
        Gán "muc_do_wfh": "DANGER" khi vi phạm BẤT KỲ điều kiện nào sau đây:
        - Đỉnh triều trạm Phú An >= 1.55m (Báo động 1 trở lên).
        - Lượng mưa ca sáng (7h-9h) HOẶC ca chiều (17h-19h) >= 15mm.
        - Tác động kết hợp: Mưa >= 5mm VÀ Triều >= 1.40m trong khung giờ cao điểm.
        - Xác suất mưa ca sáng HOẶC ca chiều >= 65%.

        🟡 TRẠNG THÁI 2: WARNING -> "CÂN NHẮC WFH"
        Gán "muc_do_wfh": "WARNING" khi rơi vào các trường hợp sau:
        - Đỉnh triều trạm Phú An từ 1.40m đến 1.54m.
        - Lượng mưa ca sáng HOẶC ca chiều từ 5mm đến 14mm.
        - Xác suất mưa ca sáng HOẶC ca chiều từ 40% đến 64%.
        - Triều dâng rơi đúng vào khung giờ tan tầm (17h00 - 19h00).

        🟢 TRẠNG THÁI 3: SAFE -> "ĐẾN VĂN PHÒNG"
        CHỈ ĐƯỢC GÁN "muc_do_wfh": "SAFE" KHI VÀ CHỈ KHI THỎA MÃN TẤT CẢ ĐIỀU KIỆN SAU:
        - Đỉnh triều trạm Phú An < 1.40m (Dưới BD1 xa).
        - Lượng mưa ca sáng VÀ ca chiều < 5mm (Khô ráo/mưa nhỏ không đáng kể).
        - Xác suất mưa cả 2 ca < 40%.

        ⚠️ CẤM TUYỆT ĐỐI: KHÔNG ĐƯỢC đưa ra khuyến nghị "ĐẾN VĂN PHÒNG" nếu có bất kỳ nguy cơ mưa giông hay triều >= 1.40m vào khung giờ 7h-9h hoặc 17h-19h.

        ========================================================================
        YÊU CẦU ĐẦU RA (OUTPUT FORMAT):
        Trả về ĐÚNG MẢNG JSON 3 PHẦN TỬ tương ứng với 3 ngày làm việc.
        LƯU Ý KỸ THUẬT:
        - Không sử dụng dấu nháy đôi (") bên trong nội dung văn bản.
        - Không xuống dòng trong bất kỳ chuỗi văn bản nào.
        - Chuỗi lý do "ly_do_wfh" phải giải thích cụ thể tác động (Ví dụ: đề cập rõ mốc giờ triều, lượng mưa ca sáng/chiều, đường nguy cơ ngập như Quốc Hương, Nguyễn Văn Hưởng).

        CẤU TRÚC JSON MẪU BẮT BUỘC:
        [
            {{
                "ngay": "DD/MM/YYYY",
                "label": "HÔM NAY",
                "dinh_trieu": "1.68m",
                "gio_dinh_trieu": "17h30",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)",
                "muc_do_wfh": "DANGER",
                "ly_do_wfh": "Triều BD3 đạt 1.68m lúc 17h30 kết hợp mưa ca chiều >20mm gây ngập sâu 30-50cm tại Nguyễn Văn Hưởng và Xuân Thủy."
            }},
            {{
                "ngay": "DD/MM/YYYY",
                "label": "NGÀY LÀM VIỆC TIẾP THEO 1",
                "dinh_trieu": "1.48m",
                "gio_dinh_trieu": "18h10",
                "bao_dong": "Dưới BD1",
                "khuyen_nghi_wfh": "CÂN NHẮC WFH",
                "muc_do_wfh": "WARNING",
                "ly_do_wfh": "Triều 1.48m lúc 18h10 kết hợp xác suất mưa ca chiều 50% có thể gây ngập nhẹ đường Quốc Hương ca đi về."
            }},
            {{
                "ngay": "DD/MM/YYYY",
                "label": "NGÀY LÀM VIỆC TIẾP THEO 2",
                "dinh_trieu": "1.32m",
                "gio_dinh_trieu": "06h30",
                "bao_dong": "Dưới BD1",
                "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
                "muc_do_wfh": "SAFE",
                "ly_do_wfh": "Thời tiết ráo mát cả 2 ca đi lại, triều thấp dưới 1.40m không ảnh hưởng giao thông Thảo Điền."
            }}
        ]
        """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
    )
    json_match = re.search(r"\[.*\]", response.text, re.DOTALL)
    if json_match:
      return json.loads(json_match.group(0), strict=False)
  except Exception:
    pass
  return fallback


@app.route("/clear-cache")
def clear_cache():
  pwd = request.args.get("pwd")
  if pwd == ADMIN_PASSWORD:
    weather_cache.clear()
    pdf_cache.clear()
    ai_cache.clear()
    return redirect(url_for("index", msg="cleared"))
  return "<h3>❌ Mật khẩu không chính xác! Không thể xóa Cache.</h3>", 403


@app.route("/")
def index():
  msg = request.args.get("msg")
  now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)

  data_ver = get_data_version(now_vn)

  today_date = now_vn.date()
  three_workdays = get_three_workdays(today_date)

  weather_list = [
      fetch_hourly_weather_thao_dien(d.strftime("%Y-%m-%d"), data_ver)
      for d in three_workdays
  ]
  pdf_date_str, pdf_bytes = fetch_latest_pdf(
      today_date.strftime("%Y-%m-%d"), data_ver
  )

  ai_data = analyze_three_workdays(
      pdf_date_str or today_date.strftime("%d/%m/%Y"),
      json.dumps(weather_list),
      pdf_bytes,
      data_ver,
  )

  cards = []
  for idx in range(3):
    d_obj = three_workdays[idx]
    item = (
        ai_data[idx]
        if idx < len(ai_data) and isinstance(ai_data[idx], dict)
        else {}
    )
    w_data = weather_list[idx]

    muc_do = str(item.get("muc_do_wfh", "SAFE")).upper()
    bg_color = "#065f46"
    icon = "✅"
    if "DANGER" in muc_do:
      bg_color = "#991b1b"
      icon = "🚨"
    elif "WARN" in muc_do:
      bg_color = "#854d0e"
      icon = "⚠️"

    cards.append({
        "label": item.get("label", "NGÀY LÀM VIỆC"),
        "date_str": d_obj.strftime("%d/%m"),
        "wfh_status": item.get("khuyen_nghi_wfh", "ĐẾN VĂN PHÒNG"),
        "wfh_reason": item.get("ly_do_wfh", "Thời tiết ổn định"),
        "bg_color": bg_color,
        "icon": icon,
        "dinh_trieu": item.get("dinh_trieu", "--"),
        "gio_trieu": item.get("gio_dinh_trieu", "--"),
        "bao_dong": item.get("bao_dong", "--"),
        "morning_rain": w_data["morning_rain"],
        "morning_prob": w_data["morning_prob"],
        "evening_rain": w_data["evening_rain"],
        "evening_prob": w_data["evening_prob"],
    })

  return render_template(
      "index.html",
      cards=cards,
      now_time=now_vn.strftime("%H:%M:%S"),
      now_date=now_vn.strftime("%d/%m/%Y"),
      msg=msg,
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
