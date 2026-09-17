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
except Exception:
  pass

if not GEMINI_API_KEY:
  st.error("⚠️ LỖI CẤU HÌNH: Chưa cài đặt GEMINI_API_KEY trong Secrets.")
  st.stop()

# 3. CSS TƯƠNG THÍCH TIZEN 3.5
st.markdown(
    """
    <style>
        .stApp { background-color: #030712 !important; }
        header, footer, #MainMenu { visibility: hidden !important; display: none !important; }
        .block-container { padding: 0.8rem !important; }
        h1, h2, h3, p, span, div { font-family: Arial, sans-serif !important; }
        div.stButton > button {
            width: 100%; background-color: #0284c7 !important; color: white !important;
            border-radius: 6px !important; border: none !important;
        }
    </style>
""",
    unsafe_allow_html=True,
)


# 4. HELPER FUNCTIONS
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

      morning_rain = round(sum(precip[7:10]), 1)
      morning_prob = max(prob[7:10]) if prob[7:10] else 0

      evening_rain = round(sum(precip[17:20]), 1)
      evening_prob = max(prob[17:20]) if prob[17:20] else 0

      return {
          "morning_rain": morning_rain,
          "morning_prob": morning_prob,
          "evening_rain": evening_rain,
          "evening_prob": evening_prob,
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


# PROMPT TỐI ƯU THEO ĐẶC THÙ KỸ THUẬT & MỤC MƯA NGẬP THẢO ĐIỀN
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
        Bạn là chuyên gia phân tích rủi ro ngập lụt chuyên sâu cho khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM) cho công ty Banqup VN.
        Tệp PDF thủy văn phát hành ngày {pdf_date_str}.
        Dữ liệu thời tiết 3 ngày làm việc (mưa ca sáng 7h-9h & mưa ca chiều 17h-19h): {dates_info_json}

        --- TRI THỨC ĐẶC THÙ THẢO ĐIỀN ---
        1. Nguyên nhân kỹ thuật:
           - Địa hình lòng chảo, cao độ nền thấp (0.5m - 1.2m), bao bọc 3 mặt bởi sông Sài Gòn.
           - Bị tác động kép: Mưa lớn + Triều cường trạm Phú An >= 1.6m (BD3) gây khóa cống xả đập, nước sông dâng ngược.
        2. Ma trận Mưa & Mức độ ngập ảnh hưởng giao thông:
           - Dưới 30mm: Ngập nhẹ (10-20cm) tại Quốc Hương (trước ĐH Văn Hiến), Đỗ Quang. Xe máy đi được.
           - 30 - 50mm: Ngập vừa (20-40cm), tràn vỉa hè tại Nguyễn Văn Hưởng, Xuân Thủy, Tống Hữu Định. Xe máy bắt đầu chết máy.
           - Trên 50mm: Ngập sâu (40-70cm) kéo dài 1-3 tiếng tại Nguyễn Văn Hưởng, Quốc Hương, Thảo Điền, Lê Văn Miến.
           - Mưa > 50mm + Triều cường Phú An >= 1.60m (BD3): NGẬP CỰC NẶNG (>70cm), tê liệt hoàn toàn giao thông toàn khu vực Thảo Điền.

        --- NHIỆM VỤ ---
        Trích xuất đỉnh triều trạm PHÚ AN từ PDF, kết hợp với dữ liệu mưa ca sáng (7h-9h) và ca chiều (17h-19h) để đánh giá khuyến nghị WFH.
        
        Quy tắc xếp loại "muc_do_wfh":
        - "DANGER": Mưa >50mm HOẶC Mưa >30mm trùng đỉnh triều >=1.60m (BD3) đúng khung giờ đi làm/về (7h-9h hoặc 17h-19h).
        - "WARNING": Mưa 30-50mm HOẶC đỉnh triều >=1.60m vào giờ cao điểm đi lại.
        - "SAFE": Mưa <30mm và triều thấp (<1.50m).

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
                "ly_do_wfh": "Tác động kép: Triều BD3 (17h30) kết hợp mưa ca chiều >30mm gây ngập sâu 20-40cm tại Nguyễn Văn Hưởng, Xuân Thủy."
            }},
            {{
                "ngay": "DD/MM/YYYY",
                "label": "NEXT WORKDAY 1",
                "dinh_trieu": "1.62m",
                "gio_dinh_trieu": "18h10",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "CÂN NHẮC WFH",
                "muc_do_wfh": "WARNING",
                "ly_do_wfh": "Đỉnh triều BD3 lúc 18h10 nguy cơ ngập nhẹ đường Quốc Hương, Đỗ Quang ca đi về."
            }},
            {{
                "ngay": "DD/MM/YYYY",
                "label": "NEXT WORKDAY 2",
                "dinh_trieu": "1.52m",
                "gio_dinh_trieu": "19h00",
                "bao_dong": "BD2",
                "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
                "muc_do_wfh": "SAFE",
                "ly_do_wfh": "Thời tiết ít mưa cả ca sáng lẫn chiều, triều cường không gây ngập."
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


# 5. FETCH DATA
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

# 6. HEADER GIAO DIỆN NATIVE
c_head1, c_head2, c_head3 = st.columns([3, 1, 1])
with c_head1:
  st.markdown(
      "<h2 style='color: #38bdf8; margin:0;'>🚨 CẢNH BÁO NGẬP & WFH Banqup"
      " VN</h2>",
      unsafe_allow_html=True,
  )
with c_head2:
  st.markdown(
      f"<div style='color: #94a3b8; font-size: 14px;'>🕒"
      f" {now_vn.strftime('%H:%M:%S')}<br>📅 {now_vn.strftime('%d/%m/%Y')}</div>",
      unsafe_allow_html=True,
  )
with c_head3:
  if st.button("🔄 Làm mới"):
    request_clear_cache_dialog()

st.markdown("---")

# 7. RENDER CONTAINERS VỚI THÔNG TIN MƯA CA SÁNG / CA CHIỀU
cols = st.columns(3)

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
    card_bg_color = "#854d0e"  # Vàng
    wfh_icon = "⚠️"

  with cols[idx]:
    with st.container():
      # Tiêu đề Ngày
      st.markdown(
          f"<h3 style='text-align: center; color: #f8fafc; margin-bottom:"
          f" 8px;'>📌 {item.get('label', '')} ({d_obj.strftime('%d/%m')})</h3>",
          unsafe_allow_html=True,
      )

      # Thẻ Khuyến nghị WFH
      st.markdown(
          f"""
                <div style="background-color: {card_bg_color}; padding: 10px; border-radius: 6px; color: #ffffff; margin-bottom: 10px;">
                    <div style="font-size: 11px; font-weight: bold;">KHUYẾN NGHỊ LÀM VIỆC:</div>
                    <div style="font-size: 18px; font-weight: bold; margin: 4px 0;">{wfh_icon} {item.get('khuyen_nghi_wfh', 'N/A')}</div>
                    <div style="font-size: 12px;">👉 {item.get('ly_do_wfh', 'N/A')}</div>
                </div>
                """,
          unsafe_allow_html=True,
      )

      # Dòng 1: Đỉnh Triều & Cấp Báo Động
      m_col1, m_col2 = st.columns(2)
      with m_col1:
        st.markdown(
            f"""
                <div style="background-color: #1e293b; padding: 6px; border-radius: 4px; text-align: center; margin-bottom: 6px;">
                    <div style="font-size: 10px; color: #94a3b8;">🌊 ĐỈNH TRIỀU</div>
                    <div style="font-size: 16px; font-weight: bold; color: #38bdf8;">{item.get('dinh_trieu', 'N/A')}</div>
                    <div style="font-size: 10px; color: #f1f5f9;">⏰ {item.get('gio_dinh_trieu', 'N/A')}</div>
                </div>
                """,
            unsafe_allow_html=True,
        )
      with m_col2:
        st.markdown(
            f"""
                <div style="background-color: #1e293b; padding: 6px; border-radius: 4px; text-align: center; margin-bottom: 6px;">
                    <div style="font-size: 10px; color: #94a3b8;">🚨 BÁO ĐỘNG</div>
                    <div style="font-size: 16px; font-weight: bold; color: #ef4444;">{item.get('bao_dong', 'N/A')}</div>
                    <div style="font-size: 10px; color: #f1f5f9;">Trạm Phú An</div>
                </div>
                """,
            unsafe_allow_html=True,
        )

      # Dòng 2: Mưa Ca Sáng (7h-9h) & Mưa Ca Chiều (17h-19h)
      with m_col1:
        st.markdown(
            f"""
                <div style="background-color: #1e293b; padding: 6px; border-radius: 4px; text-align: center;">
                    <div style="font-size: 10px; color: #94a3b8;">🌅 CA SÁNG (7h-9h)</div>
                    <div style="font-size: 16px; font-weight: bold; color: #60a5fa;">{w_data['morning_rain']} mm</div>
                    <div style="font-size: 10px; color: #f1f5f9;">☔ Xác suất {w_data['morning_prob']}%</div>
                </div>
                """,
            unsafe_allow_html=True,
        )
      with m_col2:
        st.markdown(
            f"""
                <div style="background-color: #1e293b; padding: 6px; border-radius: 4px; text-align: center;">
                    <div style="font-size: 10px; color: #94a3b8;">🌇 CA CHIỀU (17h-19h)</div>
                    <div style="font-size: 16px; font-weight: bold; color: #a78bfa;">{w_data['evening_rain']} mm</div>
                    <div style="font-size: 10px; color: #f1f5f9;">☔ Xác suất {w_data['evening_prob']}%</div>
                </div>
                """,
            unsafe_allow_html=True,
        )