import datetime
import io
import json
import re
import pandas as pd
import requests
import streamlit as st
import urllib3
from google import genai
from google.genai import types

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# CẬP NHẬT TÊN MODEL
MODEL_NAME = "gemini-3.6-flash"

# 1. CẤU HÌNH GIAO DIỆN CHUẨN TV (TIÊU ĐỀ TRANG CẬP NHẬT BANQUP VN)
st.set_page_config(
    page_title="CẢNH BÁO NGẬP & WFH Banqup VN",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 2. CSS ÉP DÙNG NATIVE FLEXBOX (TƯƠNG THÍCH 100% VỚI SAMSUNG TIZEN TV)
st.markdown(
    """
    <style>
        .stApp {
            background-color: #030712 !important;
            padding: 1vw !important;
        }
        header, footer, #MainMenu { visibility: hidden !important; display: none !important; }
        .block-container { padding: 0.5rem !important; max-width: 100% !important; }

        /* Ép Streamlit Columns không bị đè chiều rộng = 0px trên Tizen TV */
        [data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 1vw !important;
            width: 100% !important;
        }
        
        [data-testid="column"] {
            flex: 1 1 0% !important;
            min-width: 0 !important;
        }

        /* Khung hiển thị từng ngày */
        .tv-card {
            background-color: #0f172a;
            border-radius: 12px;
            padding: 1.2vw;
            border: 2px solid #1e293b;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
            margin-bottom: 0.5vw;
        }

        .metric-box {
            background-color: #1e293b;
            border-radius: 8px;
            padding: 0.6vw;
            text-align: center;
            border: 1px solid #334155;
            margin-top: 0.4vw;
        }
        
        .wfh-danger {
            background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
            border: 2px solid #ef4444; border-radius: 10px; padding: 0.8vw; color: #ffffff;
        }
        .wfh-warning {
            background: linear-gradient(135deg, #713f12 0%, #854d0e 100%);
            border: 2px solid #eab308; border-radius: 10px; padding: 0.8vw; color: #ffffff;
        }
        .wfh-safe {
            background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
            border: 2px solid #10b981; border-radius: 10px; padding: 0.8vw; color: #ffffff;
        }

        div.stButton > button {
            width: 100%;
            font-size: 1vw !important;
            font-weight: bold !important;
            background-color: #0284c7 !important;
            color: white !important;
            border-radius: 8px !important;
            border: none !important;
        }
    </style>
""",
    unsafe_allow_html=True,
)

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}

try:
  GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
  ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]
except KeyError as e:
  st.error(f"⚠️ Chưa cấu hình {e} trong Secrets.")
  st.stop()


@st.dialog("🔑 BẢO MẬT: XÁC NHẬN LÀM MỚI CACHE")
def request_clear_cache_dialog():
  st.write("Vui lòng nhập mật khẩu quản trị viên để làm mới dữ liệu:")
  pwd_input = st.text_input("Mật khẩu:", type="password")
  if st.button("Xác nhận làm mới"):
    if pwd_input == ADMIN_PASSWORD:
      st.cache_data.clear()
      st.success("✅ Đã xóa Cache thành công!")
      st.rerun()
    else:
      st.error("❌ Mật khẩu không chính xác.")


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
    pdf_bytes, dates_info_json, pdf_date_str
):
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)
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
    return [
        {
            "ngay": "N/A",
            "label": "HÔM NAY",
            "dinh_trieu": "--",
            "gio_dinh_trieu": "--",
            "bao_dong": "N/A",
            "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
            "muc_do_wfh": "SAFE",
            "ly_do_wfh": "Đang cập nhật dữ liệu thủy văn...",
        },
        {
            "ngay": "N/A",
            "label": "NEXT WORKDAY 1",
            "dinh_trieu": "--",
            "gio_dinh_trieu": "--",
            "bao_dong": "N/A",
            "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
            "muc_do_wfh": "SAFE",
            "ly_do_wfh": "Đang cập nhật dữ liệu thủy văn...",
        },
        {
            "ngay": "N/A",
            "label": "NEXT WORKDAY 2",
            "dinh_trieu": "--",
            "gio_dinh_trieu": "--",
            "bao_dong": "N/A",
            "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
            "muc_do_wfh": "SAFE",
            "ly_do_wfh": "Đang cập nhật dữ liệu thủy văn...",
        },
    ]


# --- MAIN TV LAYOUT ---
now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
today_date = now_vn.date()
three_workdays = get_three_workdays(today_date)

col_h1, col_h2, col_h3 = st.columns([3, 1, 1])
with col_h1:
  # TIÊU ĐỀ GIAO DIỆN MỚI CỦA BANQUP VN
  st.markdown(
      "<h1 style='font-size: 1.8vw; color: #38bdf8; margin:0; font-weight:"
      " 800;'>🚨 CẢNH BÁO NGẬP & WFH Banqup VN</h1>",
      unsafe_allow_html=True,
  )
with col_h2:
  st.markdown(
      f"<div style='text-align: right; font-size: 1vw; color: #94a3b8;'>🕒"
      f" {now_vn.strftime('%H:%M:%S')}<br>📅 {now_vn.strftime('%d/%m/%Y')}</div>",
      unsafe_allow_html=True,
  )
with col_h3:
  if st.button("🔄 Làm mới ngay"):
    request_clear_cache_dialog()

st.markdown("---")

pdf_url, pdf_date, pdf_bytes = fetch_latest_pdf(today_date)

weather_info_list = []
for d in three_workdays:
  r_sum, r_prob = fetch_weather_thao_dien(d.strftime("%Y-%m-%d"))
  weather_info_list.append({
      "date_str": d.strftime("%d/%m/%Y"),
      "rain_sum": r_sum,
      "rain_prob": r_prob,
  })

if pdf_bytes:
  dates_info_json = json.dumps(weather_info_list, ensure_ascii=False)
  three_days_data = analyze_three_workdays_wfh_cached(
      pdf_bytes, dates_info_json, pdf_date.strftime("%d/%m/%Y")
  )
else:
  three_days_data = analyze_three_workdays_wfh_cached(
      b"", dates_info_json, today_date.strftime("%d/%m/%Y")
  )

# DỰNG CẤU TRÚC 3 CỘT TV
cols = st.columns(3)

for idx in range(3):
  item = (
      three_days_data[idx]
      if idx < len(three_days_data)
      else three_days_data[0]
  )
  d_obj = three_workdays[idx]
  r_sum, r_prob = fetch_weather_thao_dien(d_obj.strftime("%Y-%m-%d"))

  wfh_class = "wfh-safe"
  wfh_icon = "✅"
  if item.get("muc_do_wfh") == "DANGER":
    wfh_class = "wfh-danger"
    wfh_icon = "🚨"
  elif item.get("muc_do_wfh") == "WARNING":
    wfh_class = "wfh-warning"
    wfh_icon = "⚠️"

  with cols[idx]:
    st.markdown(
        f"""
        <div class="tv-card">
            <h2 style="color: #f8fafc; margin:0 0 0.5vw 0; text-align:center; font-size: 1.3vw;">
                📌 {item.get('label', '')} ({d_obj.strftime('%d/%m')})
            </h2>
            <div class="{wfh_class}">
                <div style="font-size: 0.8vw; text-transform: uppercase; font-weight: 600;">KHUYẾN NGHỊ LÀM VIỆC:</div>
                <div style="font-size: 1.3vw; font-weight: 900; margin: 0.2vw 0;">{wfh_icon} {item.get('khuyen_nghi_wfh', 'N/A')}</div>
                <div style="font-size: 0.8vw; line-height: 1.2;">👉 {item.get('ly_do_wfh', 'N/A')}</div>
            </div>
            <div style="display: flex; gap: 0.5vw; margin-top: 0.5vw;">
                <div class="metric-box" style="flex:1;">
                    <div style="font-size: 0.75vw; color: #94a3b8;">🌊 ĐỈNH TRIỀU</div>
                    <div style="font-size: 1.4vw; font-weight: 900; color: #38bdf8;">{item.get('dinh_trieu', 'N/A')}</div>
                    <div style="font-size: 0.75vw; color: #f1f5f9;">⏰ <b>{item.get('gio_dinh_trieu', 'N/A')}</b></div>
                </div>
                <div class="metric-box" style="flex:1;">
                    <div style="font-size: 0.75vw; color: #94a3b8;">🚨 BÁO ĐỘNG</div>
                    <div style="font-size: 1.4vw; font-weight: 900; color: #ef4444;">{item.get('bao_dong', 'N/A')}</div>
                    <div style="font-size: 0.75vw; color: #f1f5f9;">Trạm Phú An</div>
                </div>
            </div>
            <div style="display: flex; gap: 0.5vw; margin-top: 0.3vw;">
                <div class="metric-box" style="flex:1;">
                    <div style="font-size: 0.75vw; color: #94a3b8;">🌧️ MƯA DỰ BÁO</div>
                    <div style="font-size: 1.4vw; font-weight: 900; color: #60a5fa;">{r_sum} mm</div>
                    <div style="font-size: 0.75vw; color: #f1f5f9;">Thảo Điền</div>
                </div>
                <div class="metric-box" style="flex:1;">
                    <div style="font-size: 0.75vw; color: #94a3b8;">☔ XÁC SUẤT</div>
                    <div style="font-size: 1.4vw; font-weight: 900; color: #a78bfa;">{r_prob}%</div>
                    <div style="font-size: 0.75vw; color: #f1f5f9;">Mưa rào</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )