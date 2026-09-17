import datetime
import json
import re
import requests
import streamlit as st
import urllib3
from google import genai
from google.genai import types

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MODEL_NAME = "gemini-3.6-flash"
BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}

st.set_page_config(
    page_title="CẢNH BÁO NGẬP & WFH Banqup VN",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD")

if not GEMINI_API_KEY:
  st.error("⚠️ LỖI CẤU HÌNH: Chưa cài đặt GEMINI_API_KEY trong Secrets.")
  st.stop()

ai_client = genai.Client(api_key=GEMINI_API_KEY)


def get_three_workdays(from_date):
  workdays = []
  current = from_date
  while len(workdays) < 3:
    if current.weekday() < 5:
      workdays.append(current)
    current += datetime.timedelta(days=1)
  return workdays


@st.cache_data(ttl=3600)
def fetch_hourly_weather_thao_dien(target_date_str):
  url = f"https://api.open-meteo.com/v1/forecast?latitude=10.8031&longitude=106.7324&hourly=precipitation,precipitation_probability&timezone=Asia%2FBangkok&start_date={target_date_str}&end_date={target_date_str}"
  try:
    res = requests.get(url, timeout=3)
    if res.status_code == 200:
      data = res.json()
      precip = data.get("hourly", {}).get("precipitation", [])
      prob = data.get("hourly", {}).get("precipitation_probability", [])
      return {
          "morning_rain": (
              round(sum(precip[7:10]), 1) if len(precip) >= 10 else 0.0
          ),
          "morning_prob": (
              max(prob[7:10]) if len(prob) >= 10 and prob[7:10] else 0
          ),
          "evening_rain": (
              round(sum(precip[17:20]), 1) if len(precip) >= 20 else 0.0
          ),
          "evening_prob": (
              max(prob[17:20]) if len(prob) >= 20 and prob[17:20] else 0
          ),
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


@st.cache_data(ttl=7200)
def fetch_latest_pdf(today_date):
  for i in range(3):
    check_date = today_date - datetime.timedelta(days=i)
    pdf_url = build_pdf_url(check_date)
    try:
      res = requests.get(pdf_url, headers=HEADERS, timeout=2, verify=False)
      if res.status_code == 200 and len(res.content) > 1000:
        return pdf_url, check_date, res.content
    except Exception:
      continue
  return None, None, None


@st.cache_data(ttl=86400)
def analyze_three_workdays_wfh_cached(pdf_bytes, dates_info_json, pdf_date_str):
  fallback_response = [
      {
          "ngay": "N/A",
          "label": "HÔM NAY",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "17h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết và thủy văn ổn định.",
      },
      {
          "ngay": "N/A",
          "label": "NEXT WORKDAY 1",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "18h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết và thủy văn ổn định.",
      },
      {
          "ngay": "N/A",
          "label": "NEXT WORKDAY 2",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "19h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết và thủy văn ổn định.",
      },
  ]
  if not pdf_bytes or len(pdf_bytes) < 100:
    return fallback_response

  try:
    prompt = f"""
        Bạn là chuyên gia phân tích rủi ro ngập lụt khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM) cho công ty Banqup VN.
        Tệp PDF thủy văn phát hành ngày {pdf_date_str}. Dữ liệu thời tiết: {dates_info_json}
        
        Trả về ĐÚNG CẤU TRÚC JSON MẢNG:
        [
            {{"ngay": "DD/MM/YYYY", "label": "HÔM NAY", "dinh_trieu": "1.68m", "gio_dinh_trieu": "17h30", "bao_dong": "BD3", "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)", "muc_do_wfh": "DANGER", "ly_do_wfh": "Triều BD3 kết hợp mưa ca chiều trên 30mm gây ngập sâu."}},
            {{"ngay": "DD/MM/YYYY", "label": "NEXT WORKDAY 1", "dinh_trieu": "1.62m", "gio_dinh_trieu": "18h10", "bao_dong": "BD3", "khuyen_nghi_wfh": "CÂN NHẮC WFH", "muc_do_wfh": "WARNING", "ly_do_wfh": "Triều BD3 lúc 18h10 nguy cơ ngập nhẹ ca đi về."}},
            {{"ngay": "DD/MM/YYYY", "label": "NEXT WORKDAY 2", "dinh_trieu": "1.52m", "gio_dinh_trieu": "19h00", "bao_dong": "BD2", "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG", "muc_do_wfh": "SAFE", "ly_do_wfh": "Thời tiết thuận lợi cả 2 ca đi lại."}}
        ]
        """
    response = ai_client.models.generate_content(
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
    pdf_bytes, dates_info_json, pdf_date_label
)

# HTML/CSS SIÊU PHẲNG - BỎ HOÀN TOÀN BORDER-RADIUS VÀ BORDER LỒNG
cards_code = ""
for idx in range(3):
  raw_item = (
      three_days_data[idx]
      if (idx < len(three_days_data) and isinstance(three_days_data[idx], dict))
      else {}
  )

  d_obj = three_workdays[idx]
  w_data = fetch_hourly_weather_thao_dien(d_obj.strftime("%Y-%m-%d"))

  label_str = str(raw_item.get("label", "NGÀY LÀM VIỆC"))
  wfh_str = str(raw_item.get("khuyen_nghi_wfh", "ĐẾN VĂN PHÒNG"))
  ly_do_str = str(raw_item.get("ly_do_wfh", "Thời tiết ổn định"))
  trieu_str = str(raw_item.get("dinh_trieu", "--"))
  gio_str = str(raw_item.get("gio_dinh_trieu", "--"))
  bd_str = str(raw_item.get("bao_dong", "--"))
  muc_do = str(raw_item.get("muc_do_wfh", "SAFE")).upper()

  card_bg_color = "#065f46"
  status_icon = "✅"
  if "DANGER" in muc_do:
    card_bg_color = "#991b1b"
    status_icon = "🚨"
  elif "WARN" in muc_do:
    card_bg_color = "#854d0e"
    status_icon = "⚠️"

  # SỬ DỤNG BẢNG HTML4 CỔ ĐIỂN - GÓC VUÔNG TUYỆT ĐỐI (NO BORDER-RADIUS)
  cards_code += f"""
    <td width="33%" valign="top" style="padding: 2px; height: 1000px">
        <table width="100%" border="0" cellspacing="0" cellpadding="4" style="background-color: #0f172a;">
            <tr>
                <td align="center" style="font-size: 13px; font-weight: bold; color: #f8fafc; background-color: #1e293b;">
                    📌 {label_str} ({d_obj.strftime('%d/%m')})
                </td>
            </tr>
            <tr>
                <td style="background-color: {card_bg_color}; color: #ffffff; padding: 6px;">
                    <font style="font-size: 9px; font-weight: bold; text-transform: uppercase;">KHUYẾN NGHỊ LÀM VIỆC:</font><br>
                    <font style="font-size: 13px; font-weight: bold;">{status_icon} {wfh_str}</font><br>
                    <font style="font-size: 10px;">👉 {ly_do_str}</font>
                </td>
            </tr>
            <tr>
                <td style="background-color: #1e293b; color: #94a3b8; font-size: 10px; padding: 4px;">
                    🌊 TRIỀU: <font color="#38bdf8"><b>{trieu_str}</b></font> (⏰ {gio_str}) | <font color="#ef4444"><b>{bd_str}</b></font>
                </td>
            </tr>
            <tr>
                <td style="background-color: #1e293b; color: #94a3b8; font-size: 10px; padding: 4px;">
                    🌅 SÁNG (7h-9h): <font color="#60a5fa"><b>{w_data['morning_rain']} mm</b></font> (☔ {w_data['morning_prob']}%)
                </td>
            </tr>
            <tr>
                <td style="background-color: #1e293b; color: #94a3b8; font-size: 10px; padding: 4px;">
                    🌇 CHIỀU (17h-19h): <font color="#a78bfa"><b>{w_data['evening_rain']} mm</b></font> (☔ {w_data['evening_prob']}%)
                </td>
            </tr>
        </table>
    </td>
    """

# KHUNG HTML TỔNG - TRIỆT TIỆU TOÀN BỘ CSS3 NÂNG CAO
pure_tizen_canvas = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    html, body {{
        background-color: #030712 !important;
        color: #f8fafc !important;
        font-family: Arial, Helvetica, sans-serif !important;
        margin: 0 !important;
        padding: 2px !important;
    }}
</style>
</head>
<body>
    <table width="100%" border="0" cellspacing="0" cellpadding="2" style="margin-bottom: 4px;">
        <tr>
            <td style="font-size: 14px; font-weight: bold; color: #38bdf8;">
                🚨 CẢNH BÁO NGẬP & WFH Banqup VN
            </td>
            <td align="right" style="font-size: 10px; color: #94a3b8;">
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

st.html(pure_tizen_canvas)

if st.button("🔄 Làm mới dữ liệu ngay"):
  request_clear_cache_dialog()