import datetime
import json
import re
import pandas as pd
import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# CONFIGURATION
MODEL_NAME = "gemini-3.6-flash"
BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}

# 1. PAGE SETUP
st.set_page_config(
    page_title="CẢNH BÁO NGẬP & WFH Banqup VN",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 2. CHECK SECRETS SAFELY
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD")

if not GEMINI_API_KEY:
  st.error("⚠️ LỖI CẤU HÌNH: Chưa cài đặt GEMINI_API_KEY trong Secrets.")
  st.stop()


# 3. HELPER FUNCTIONS
def get_three_workdays(from_date):
  workdays = []
  current = from_date
  while len(workdays) < 3:
    if current.weekday() < 5:
      workdays.append(current)
    current += datetime.timedelta(days=1)
  return workdays


@st.cache_data(ttl=86400)
def fetch_hourly_weather_thao_dien(target_date_str):
  url = f"https://api.open-meteo.com/v1/forecast?latitude=10.8031&longitude=106.7324&hourly=precipitation,precipitation_probability&timezone=Asia%2FBangkok&start_date={target_date_str}&end_date={target_date_str}"
  try:
    res = requests.get(url, timeout=5)
    if res.status_code == 200:
      data = res.json()
      precip = data["hourly"]["precipitation"]
      prob = data["hourly"]["precipitation_probability"]
      return {
          "morning_rain": round(sum(precip[7:10]), 1),
          "morning_prob": max(prob[7:10]) if prob[7:10] else 0,
          "evening_rain": round(sum(precip[17:20]), 1),
          "evening_prob": max(prob[17:20]) if prob[17:20] else 0,
      }
  except Exception:
    pass
  return {
      "morning_rain": 0.0,
      "morning_prob": 0,
      "evening_rain": 0.0,
      "evening_prob": 0,
  }


def build_pdf_url(target_date):
  return f"{BASE_DOMAIN}/phocadownload/{target_date.strftime('%Y')}/{target_date.strftime('%m-%Y')}/HCMC_TVHN_{target_date.strftime('%Y%m%d')}.pdf"


@st.cache_data(ttl=86400)
def fetch_latest_pdf(today_date):
  for i in range(5):
    check_date = today_date - datetime.timedelta(days=i)
    pdf_url = build_pdf_url(check_date)
    try:
      res = requests.get(pdf_url, headers=HEADERS, timeout=5, verify=False)
      if res.status_code == 200 and len(res.content) > 1000:
        return pdf_url, check_date, res.content
    except Exception:
      continue
  return None, None, None


@st.cache_data(ttl=86400)
def analyze_three_workdays_wfh_cached(
    pdf_bytes, dates_info_json, pdf_date_str, api_key
):
  fallback_response = [
      {
          "ngay": "N/A",
          "label": "HÔM NAY",
          "dinh_trieu": "--",
          "gio_dinh_trieu": "--",
          "bao_dong": "N/A",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Dữ liệu đang được cập nhật...",
      },
      {
          "ngay": "N/A",
          "label": "NEXT WORKDAY 1",
          "dinh_trieu": "--",
          "gio_dinh_trieu": "--",
          "bao_dong": "N/A",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Dữ liệu đang được cập nhật...",
      },
      {
          "ngay": "N/A",
          "label": "NEXT WORKDAY 2",
          "dinh_trieu": "--",
          "gio_dinh_trieu": "--",
          "bao_dong": "N/A",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Dữ liệu đang được cập nhật...",
      },
  ]
  if not pdf_bytes or len(pdf_bytes) < 100:
    return fallback_response
  try:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = f"""
        Bạn là chuyên gia phân tích rủi ro ngập lụt khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM) cho công ty Banqup VN.
        Tệp PDF thủy văn phát hành ngày {pdf_date_str}. Dữ liệu thời tiết: {dates_info_json}
        Đặc thù: Địa hình lòng chảo, bao bọc 3 mặt bởi sông Sài Gòn. Tác động kép Mưa + Triều Phú An >= 1.6m (BD3) gây ngập cực nặng.
        Trích xuất đỉnh triều trạm PHÚ AN, kết hợp mưa ca sáng (7h-9h)/chiều (17h-19h) và đưa ra gợi ý WFH.
        Trả về ĐÚNG CẤU TRÚC JSON MẢNG:
        [
            {{"ngay": "DD/MM/YYYY", "label": "HÔM NAY", "dinh_trieu": "1.68m", "gio_dinh_trieu": "17h30", "bao_dong": "BD3", "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)", "muc_do_wfh": "DANGER", "ly_do_wfh": "Triều BD3 (17h30) kết hợp mưa ca chiều >30mm gây ngập sâu."}},
            {{"ngay": "DD/MM/YYYY", "label": "NEXT WORKDAY 1", "dinh_trieu": "1.62m", "gio_dinh_trieu": "18h10", "bao_dong": "BD3", "khuyen_nghi_wfh": "CÂN NHẮC WFH", "muc_do_wfh": "WARNING", "ly_do_wfh": "Triều BD3 lúc 18h10 nguy cơ ngập nhẹ ca đi về."}},
            {{"ngay": "DD/MM/YYYY", "label": "NEXT WORKDAY 2", "dinh_trieu": "1.52m", "gio_dinh_trieu": "19h00", "bao_dong": "BD2", "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG", "muc_do_wfh": "SAFE", "ly_do_wfh": "Thời tiết thuận lợi cả 2 ca đi lại."}}
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
    clean_json = json_match.group(0) if json_match else response.text.strip()
    return json.loads(clean_json)
  except Exception:
    return fallback_response


@st.dialog("🔑 BẢO MẬT: XÁC NHẬN LÀM MỚI CACHE")
def request_clear_cache_dialog():
  st.write("Vui lòng nhập mật khẩu quản trị viên để làm mới dữ liệu:")
  pwd_input = st.text_input("Mật khẩu:", type="password")
  if st.button("Xác nhận làm mới"):
    if ADMIN_PASSWORD and pwd_input == ADMIN_PASSWORD:
      st.cache_data.clear()
      st.success("✅ Đã xóa Cache thành công!")
      st.rerun()
    else:
      st.error("❌ Mật khẩu không chính xác.")


# 4. DATA PROCESSING
now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
today_date = now_vn.date()
three_workdays = get_three_workdays(today_date)

pdf_url, pdf_date, pdf_bytes = fetch_latest_pdf(today_date)

weather_info_list = []
for d in three_workdays:
  w_data = fetch_hourly_weather_thao_dien(d.strftime("%Y-%m-%d"))
  weather_info_list.append({
      "date_str": d.strftime("%d/%m/%Y"),
      "morning_commute_rain_mm": w_data["morning_rain"],
      "morning_commute_prob_pct": w_data["morning_prob"],
      "evening_commute_rain_mm": w_data["evening_rain"],
      "evening_commute_prob_pct": w_data["evening_prob"],
  })

dates_info_json = json.dumps(weather_info_list, ensure_ascii=False)
pdf_date_label = (
    pdf_date.strftime("%d/%m/%Y")
    if pdf_date
    else today_date.strftime("%d/%m/%Y")
)
three_days_data = analyze_three_workdays_wfh_cached(
    pdf_bytes, dates_info_json, pdf_date_label, GEMINI_API_KEY
)

# 5. DỰNG CANVAS HTML SIÊU BẸT VÀ PHẲNG NATIVE CHO ST.HTML()
# Không dùng CSS Flexbox, không dùng div lồng phức tạp. Sử dụng Table tiêu chuẩn Chromium v47.
cards_code = ""
for idx in range(3):
  item = (
      three_days_data[idx]
      if idx < len(three_days_data)
      else three_days_data[0]
  )
  d_obj = three_workdays[idx]
  w_data = fetch_hourly_weather_thao_dien(d_obj.strftime("%Y-%m-%d"))

  card_bg_color = "#065f46"  # Xanh
  wfh_icon = "✅"
  if item.get("muc_do_wfh") == "DANGER":
    card_bg_color = "#991b1b"  # Đỏ
    wfh_icon = "🚨"
  elif item.get("muc_do_wfh") == "WARNING":
    card_bg_color = "#854d0e"  # Cam/Vàng
    wfh_icon = "⚠️"

  cards_code += f"""
    <td width="33%" valign="top" style="padding: 2px;">
        <table width="100%" border="0" cellspacing="0" cellpadding="6" style="background-color: #0f172a; border: 1px solid #1e293b;">
            <tr>
                <td align="center" style="font-size: 14px; font-weight: bold; color: #f8fafc; border-bottom: 1px solid #1e293b;">
                    📌 {item.get('label', '')} ({d_obj.strftime('%d/%m')})
                </td>
            </tr>
            <tr>
                <td style="background-color: {card_bg_color}; color: #ffffff;">
                    <div style="font-size: 10px; font-weight: bold;">KHUYẾN NGHỊ LÀM VIỆC:</div>
                    <div style="font-size: 14px; font-weight: bold; margin: 2px 0;">{wfh_icon} {item.get('khuyen_nghi_wfh', 'N/A')}</div>
                    <div style="font-size: 10px;">👉 {item.get('ly_do_wfh', 'N/A')}</div>
                </td>
            </tr>
            <tr>
                <td style="background-color: #1e293b; font-size: 11px; color: #94a3b8; border-bottom: 1px solid #0f172a;">
                    🌊 TRIỀU: <b style="color: #38bdf8;">{item.get('dinh_trieu', 'N/A')}</b> (⏰ {item.get('gio_dinh_trieu', 'N/A')}) | <b style="color: #ef4444;">{item.get('bao_dong', 'N/A')}</b>
                </td>
            </tr>
            <tr>
                <td style="background-color: #1e293b; font-size: 11px; color: #94a3b8; border-bottom: 1px solid #0f172a;">
                    🌅 SÁNG (7h-9h): <b style="color: #60a5fa;">{w_data['morning_rain']} mm</b> (☔ {w_data['morning_prob']}%)
                </td>
            </tr>
            <tr>
                <td style="background-color: #1e293b; font-size: 11px; color: #94a3b8;">
                    🌇 CHIỀU (17h-19h): <b style="color: #a78bfa;">{w_data['evening_rain']} mm</b> (☔ {w_data['evening_prob']}%)
                </td>
            </tr>
        </table>
    </td>
    """

pure_tizen_canvas = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{
        background-color: #030712;
        color: #f8fafc;
        font-family: Arial, sans-serif;
        margin: 0;
        padding: 4px;
    }}
</style>
</head>
<body>
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 6px;">
        <tr>
            <td style="font-size: 16px; font-weight: bold; color: #38bdf8;">
                🚨 CẢNH BÁO NGẬP & WFH Banqup VN
            </td>
            <td align="right" style="font-size: 11px; color: #94a3b8;">
                🕒 {now_vn.strftime('%H:%M:%S')} | 📅 {now_vn.strftime('%d/%m/%Y')}
            </td>
        </tr>
    </table>

    <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
            {cards_code}
        </tr>
    </table>
</body>
</html>
"""

# OUTPUT TRỰC TIẾP QUA ST.HTML VỚI ĐỊNH DẠNG FULL CANVAS TIZEN
st.html(pure_tizen_canvas)

# NÚT BẤM CLEAR CACHE ADMIN (NATIVE)
if st.button("🔄 Làm mới dữ liệu ngay"):
  request_clear_cache_dialog()