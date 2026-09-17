import datetime
import io
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
GEMINI_API_KEY = None
ADMIN_PASSWORD = None

try:
  if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
  if "ADMIN_PASSWORD" in st.secrets:
    ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]
except Exception as e:
  pass

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
def fetch_weather_thao_dien(target_date_str):
  url = f"https://api.open-meteo.com/v1/forecast?latitude=10.8031&longitude=106.7324&daily=precipitation_sum,precipitation_probability_max&timezone=Asia%2FBangkok&start_date={target_date_str}&end_date={target_date_str}"
  try:
    res = requests.get(url, timeout=5)
    if res.status_code == 200:
      data = res.json()
      rain_sum = data["daily"]["precipitation_sum"][0]
      rain_prob = data["daily"]["precipitation_probability_max"][0]
      return rain_sum, rain_prob
  except Exception:
    pass
  return 0, 0


def build_pdf_url(target_date):
  yyyy = target_date.strftime("%Y")
  mm = target_date.strftime("%m")
  dd = target_date.strftime("%d")
  return f"{BASE_DOMAIN}/phocadownload/{yyyy}/{mm}-{yyyy}/HCMC_TVHN_{yyyy}{mm}{dd}.pdf"


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
        Bạn là hệ thống AI đánh giá rủi ro ngập lụt THẢO ĐIỀN (TP. Thủ Đức, TP.HCM).
        Tệp PDF thủy văn phát hành ngày {pdf_date_str}. Dữ liệu thời tiết 3 ngày: {dates_info_json}

        Nhiệm vụ: Trích xuất thông số trạm PHÚ AN và đưa ra khuyến nghị WFH cho từng ngày.
        Trả về ĐÚNG CẤU TRÚC JSON MẢNG sau (Không có ký tự thừa):
        [
            {{
                "ngay": "DD/MM/YYYY",
                "label": "HÔM NAY",
                "dinh_trieu": "1.68m",
                "gio_dinh_trieu": "17h30",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)",
                "muc_do_wfh": "DANGER",
                "ly_do_wfh": "Cảnh báo ngập sâu do đỉnh triều BD3 kết hợp nguy cơ mưa."
            }},
            {{
                "ngay": "DD/MM/YYYY",
                "label": "NEXT WORKDAY 1",
                "dinh_trieu": "1.62m",
                "gio_dinh_trieu": "18h10",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "CÂN NHẮC WFH",
                "muc_do_wfh": "WARNING",
                "ly_do_wfh": "Đỉnh triều cao xấp xỉ BD3 vào giờ tan tầm."
            }},
            {{
                "ngay": "DD/MM/YYYY",
                "label": "NEXT WORKDAY 2",
                "dinh_trieu": "1.52m",
                "gio_dinh_trieu": "19h00",
                "bao_dong": "BD2",
                "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
                "muc_do_wfh": "SAFE",
                "ly_do_wfh": "Triều cường ở mức BD2, thời tiết ít mưa."
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
    raw_text = response.text
    json_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    clean_json = json_match.group(0) if json_match else raw_text.strip()
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
      st.error("❌ Mật khẩu không chính xác hoặc chưa cấu hình PASSWORD.")


# 4. FETCH DATA
now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
today_date = now_vn.date()
three_workdays = get_three_workdays(today_date)

pdf_url, pdf_date, pdf_bytes = fetch_latest_pdf(today_date)

weather_info_list = []
for d in three_workdays:
  r_sum, r_prob = fetch_weather_thao_dien(d.strftime("%Y-%m-%d"))
  weather_info_list.append({
      "date_str": d.strftime("%d/%m/%Y"),
      "rain_sum": r_sum,
      "rain_prob": r_prob,
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

# 5. RENDER HTML TIZEN 3.5 COMPATIBLE
cards_html = ""
for idx in range(3):
  item = (
      three_days_data[idx]
      if idx < len(three_days_data)
      else three_days_data[0]
  )
  d_obj = three_workdays[idx]
  r_sum, r_prob = fetch_weather_thao_dien(d_obj.strftime("%Y-%m-%d"))

  bg_color = "linear-gradient(135deg, #064e3b 0%, #065f46 100%)"
  border_color = "#10b981"
  wfh_icon = "✅"

  if item.get("muc_do_wfh") == "DANGER":
    bg_color = "linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%)"
    border_color = "#ef4444"
    wfh_icon = "🚨"
  elif item.get("muc_do_wfh") == "WARNING":
    bg_color = "linear-gradient(135deg, #713f12 0%, #854d0e 100%)"
    border_color = "#eab308"
    wfh_icon = "⚠️"

  cards_html += f"""
    <td width="33%" valign="top" style="padding: 0 6px;">
        <div style="background-color: #0f172a; border-radius: 12px; padding: 14px; border: 2px solid #1e293b;">
            <h2 style="color: #f8fafc; margin: 0 0 8px 0; text-align: center; font-size: 18px;">
                📌 {item.get('label', '')} ({d_obj.strftime('%d/%m')})
            </h2>
            <div style="background: {bg_color}; border: 2px solid {border_color}; border-radius: 8px; padding: 10px; color: #ffffff; margin-bottom: 10px;">
                <div style="font-size: 11px; text-transform: uppercase; font-weight: bold;">KHUYẾN NGHỊ LÀM VIỆC:</div>
                <div style="font-size: 18px; font-weight: 900; margin: 2px 0;">{wfh_icon} {item.get('khuyen_nghi_wfh', 'N/A')}</div>
                <div style="font-size: 11px; line-height: 1.2;">👉 {item.get('ly_do_wfh', 'N/A')}</div>
            </div>
            
            <table width="100%" cellspacing="3" cellpadding="0" border="0">
                <tr>
                    <td width="50%" align="center" style="background-color: #1e293b; border-radius: 6px; padding: 6px; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #94a3b8;">🌊 ĐỈNH TRIỀU</div>
                        <div style="font-size: 18px; font-weight: bold; color: #38bdf8;">{item.get('dinh_trieu', 'N/A')}</div>
                        <div style="font-size: 11px; color: #f1f5f9;">⏰ <b>{item.get('gio_dinh_trieu', 'N/A')}</b></div>
                    </td>
                    <td width="50%" align="center" style="background-color: #1e293b; border-radius: 6px; padding: 6px; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #94a3b8;">🚨 BÁO ĐỘNG</div>
                        <div style="font-size: 18px; font-weight: bold; color: #ef4444;">{item.get('bao_dong', 'N/A')}</div>
                        <div style="font-size: 11px; color: #f1f5f9;">Trạm Phú An</div>
                    </td>
                </tr>
                <tr>
                    <td width="50%" align="center" style="background-color: #1e293b; border-radius: 6px; padding: 6px; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #94a3b8;">🌧️ MƯA DỰ BÁO</div>
                        <div style="font-size: 18px; font-weight: bold; color: #60a5fa;">{r_sum} mm</div>
                        <div style="font-size: 11px; color: #f1f5f9;">Thảo Điền</div>
                    </td>
                    <td width="50%" align="center" style="background-color: #1e293b; border-radius: 6px; padding: 6px; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #94a3b8;">☔ XÁC SUẤT</div>
                        <div style="font-size: 18px; font-weight: bold; color: #a78bfa;">{r_prob}%</div>
                        <div style="font-size: 11px; color: #f1f5f9;">Mưa rào</div>
                    </td>
                </tr>
            </table>
        </div>
    </td>
    """

full_page_html = f"""
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
            padding: 8px;
        }}
    </style>
</head>
<body>
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 8px;">
        <tr>
            <td>
                <h1 style="color: #38bdf8; margin: 0; font-size: 22px;">🚨 CẢNH BÁO NGẬP & WFH Banqup VN</h1>
            </td>
            <td align="right" style="color: #94a3b8; font-size: 14px;">
                🕒 {now_vn.strftime('%H:%M:%S')} | 📅 {now_vn.strftime('%d/%m/%Y')}
            </td>
        </tr>
    </table>
    <hr style="border: 0; border-top: 1px solid #334155; margin-bottom: 10px;">
    
    <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
            {cards_html}
        </tr>
    </table>
</body>
</html>
"""

# OUTPUT HTML CANVAS
st.html(full_page_html)

# ADMIN ACTION BUTTON
if st.button("🔄 Làm mới dữ liệu ngay"):
  request_clear_cache_dialog()