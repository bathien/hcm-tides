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
from streamlit_autorun import autorun

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. CẤU HÌNH GIAO DIỆN MÀN HÌNH TV 43 INCH
st.set_page_config(
    page_title="HỆ THỐNG CẢNH BÁO NGẬP & WFH Banqup HCM",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Tự động làm mới trang mỗi 60 giây
autorun(interval=60000, key="tv_auto_refresh")

# CSS TỰ ĐỘNG PHÓNG TO CHỮ & ĐỔI MÀU NỀN CẢNH BÁO WFH
st.markdown(
    """
    <style>
        html, body, [class*="css"] { font-size: 22px !important; }
        .metric-card {
            background-color: #1e293b;
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            border: 2px solid #334155;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }
        .metric-title { font-size: 22px; color: #94a3b8; font-weight: 600; margin-bottom: 8px; }
        .metric-value { font-size: 50px; font-weight: 900; color: #38bdf8; }
        .metric-sub { font-size: 20px; color: #f1f5f9; margin-top: 8px; }
        
        /* Thẻ Khuyên làm việc tại nhà (WFH) */
        .wfh-card-danger {
            background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
            border: 3px solid #ef4444;
            border-radius: 16px;
            padding: 25px;
            color: white;
        }
        .wfh-card-warning {
            background: linear-gradient(135deg, #713f12 0%, #854d0e 100%);
            border: 3px solid #eab308;
            border-radius: 16px;
            padding: 25px;
            color: white;
        }
        .wfh-card-safe {
            background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
            border: 3px solid #10b981;
            border-radius: 16px;
            padding: 25px;
            color: white;
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
except KeyError:
  st.error("⚠️ Chưa cài đặt GEMINI_API_KEY trong Secrets.")
  st.stop()


# 2. TỰ ĐỘNG XÓA CACHE VÀO 11:00 SÁNG (UTC+7)
def check_clear_cache():
  now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  if now_vn.hour == 11 and now_vn.minute in [0, 1, 2]:
    st.cache_data.clear()


check_clear_cache()


# 3. HÀM LẤY DỰ BÁO MƯA TP.HCM TỪ OPEN-METEO API (MIỄN PHÍ)
@st.cache_data(ttl=3600)
def fetch_weather_rain_hcm():
  """Tọa độ TP.HCM: 10.8231, 106.6297"""
  url = "https://api.open-meteo.com/v1/forecast?latitude=10.8231&longitude=106.6297&daily=precipitation_sum,precipitation_probability_max&timezone=Asia%2FBangkok"
  try:
    res = requests.get(url, timeout=5)
    if res.status_code == 200:
      data = res.json()
      rain_sum = data["daily"]["precipitation_sum"][0]  # Lượng mưa (mm)
      rain_prob = data["daily"]["precipitation_probability_max"][
          0
      ]  # Xác suất mưa (%)
      return rain_sum, rain_prob
  except Exception:
    pass
  return 0, 0


def build_pdf_url(target_date):
  yyyy = target_date.strftime("%Y")
  mm = target_date.strftime("%m")
  dd = target_date.strftime("%d")
  return f"{BASE_DOMAIN}/phocadownload/{yyyy}/{mm}-{yyyy}/HCMC_TVHN_{yyyy}{mm}{dd}.pdf"


@st.cache_data(ttl=1800)
def fetch_latest_pdf():
  today = datetime.date.today()
  for i in range(7):
    check_date = today - datetime.timedelta(days=i)
    pdf_url = build_pdf_url(check_date)
    try:
      res = requests.get(pdf_url, headers=HEADERS, timeout=5, verify=False)
      if res.status_code == 200 and len(res.content) > 1000:
        return pdf_url, check_date, res.content
    except Exception:
      continue
  return None, None, None


# 4. AI ĐÁNH GIÁ TỔNG HỢP: TRIỀU CƯỜNG + MƯA LỚN = NÊN WFH KHÔNG?
def analyze_flood_and_wfh(pdf_bytes, rain_sum, rain_prob):
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
        Bạn là hệ thống trí tuệ nhân tạo hỗ trợ đưa ra quyết định vận hành doanh nghiệp.
        Hãy đọc tệp PDF thủy văn TP.HCM và kết hợp với dữ liệu dự báo thời tiết sau:
        - Lượng mưa dự báo trong ngày tại TP.HCM: {rain_sum} mm.
        - Xác suất mưa lớn: {rain_prob} %.

        Nhiệm vụ:
        1. Trích xuất thông số TRẠM PHÚ AN (Mực nước đỉnh triều cao nhất, Giờ đỉnh triều, Cấp báo động BD1/BD2/BD3).
        2. Đánh giá nguy cơ cộng hưởng ngập (Mưa + Triều cường) để khuyến nghị chế độ làm việc:
           - "KHUYÊN NÊN WFH (LÀM VIỆC TẠI NHÀ)": Nếu Triều cường >= BD2 HOẶC (Triều cường >= BD1 VÀ Lượng mưa > 20mm).
           - "CÂN NHẮC WFH / ĐI LẠI TRÁNH GIỜ CAO ĐIỂM": Nếu Triều cường BD1 hoặc Mưa rải rác.
           - "ĐẾN VĂN PHÒNG BÌNH THƯỜNG": Nếu Thủy văn an toàn và không mưa lớn.

        Trả về kết quả CHÍNH XÁC ở định dạng JSON (Không kèm bất kỳ từ nào khác):
        {{
            "dinh_trieu": "1.68m",
            "gio_dinh_trieu": "17h30",
            "bao_dong": "BD3",
            "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)",
            "muc_do_wfh": "DANGER",
            "ly_do_wfh": "Cảnh báo ngập nặng do triều cường BD3 kết hợp nguy cơ mưa lớn vào giờ tan tầm (16h30 - 19h00)."
        }}
        Lưu ý: "muc_do_wfh" chỉ nhận 1 trong 3 giá trị: "DANGER" (Nguy hiểm/Nên WFH), "WARNING" (Cảnh báo/Cân nhắc), "SAFE" (Bình thường).
        """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
    )

    clean_json = re.sub(r"```json|```", "", response.text).strip()
    return json.loads(clean_json)
  except Exception:
    return None


# --- GIAO DIỆN MÀN HÌNH TV ---
now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
  st.markdown(
      "<h1 style='font-size: 42px; color: #38bdf8; margin:0;'>🚨 HỆ THỐNG CẢNH"
      " BÁO NGẬP & ĐỀ XUẤT LÀM VIỆC TẠI NHÀ (WFH)</h1>",
      unsafe_allow_html=True,
  )
with col_h2:
  st.markdown(
      f"<div style='text-align: right; font-size: 22px; color: #94a3b8;'>🕒"
      f" {now_vn.strftime('%H:%M:%S')} | 📅 {now_vn.strftime('%d/%m/%Y')}</div>",
      unsafe_allow_html=True,
  )

st.markdown("---")

# TẢI DỮ LIỆU
with st.spinner("Đang tổng hợp dữ liệu Thủy văn và Thời tiết mưa..."):
  pdf_url, latest_date, pdf_bytes = fetch_latest_pdf()
  rain_sum, rain_prob = fetch_weather_rain_hcm()

if pdf_url and latest_date:
  data = analyze_flood_and_wfh(pdf_bytes, rain_sum, rain_prob)

  if data:
    # Xác định màu sắc Thẻ Khuyến Nghị WFH
    wfh_style = "wfh-card-safe"
    wfh_icon = "✅"
    if data.get("muc_do_wfh") == "DANGER":
      wfh_style = "wfh-card-danger"
      wfh_icon = "🚨"
    elif data.get("muc_do_wfh") == "WARNING":
      wfh_style = "wfh-card-warning"
      wfh_icon = "⚠️"

    # 1. THẺ ĐỀ XUẤT WFH CỠ ĐẠI HÀNG ĐẦU MÀN HÌNH TV
    st.markdown(
        f"""
        <div class="{wfh_style}">
            <div style="font-size: 24px; text-transform: uppercase; letter-spacing: 2px;">KHUYẾN NGHỊ LÀM VIỆC HẰNG NGÀY:</div>
            <div style="font-size: 48px; font-weight: 900; margin: 10px 0;">{wfh_icon} {data.get('khuyen_nghi_wfh', 'N/A')}</div>
            <div style="font-size: 24px; line-height: 1.4;">👉 <b>Lý do:</b> {data.get('ly_do_wfh', 'N/A')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. BỐN THẺ THÔNG SỐ CHI TIẾT
    c1, c2, c3, c4 = st.columns(4)

    with c1:
      st.markdown(
          f"""
            <div class="metric-card">
                <div class="metric-title">🌊 ĐỈNH TRIỀU PHÚ AN</div>
                <div class="metric-value">{data.get('dinh_trieu', 'N/A')}</div>
                <div class="metric-sub">⏰ Đỉnh triều: <b>{data.get('gio_dinh_trieu', 'N/A')}</b></div>
            </div>
            """,
          unsafe_allow_html=True,
      )

    with c2:
      st.markdown(
          f"""
            <div class="metric-card">
                <div class="metric-title">🚨 CẤP BÁO ĐỘNG</div>
                <div class="metric-value" style="color: #ef4444;">{data.get('bao_dong', 'N/A')}</div>
                <div class="metric-sub">Sông Sài Gòn</div>
            </div>
            """,
          unsafe_allow_html=True,
      )

    with c3:
      st.markdown(
          f"""
            <div class="metric-card">
                <div class="metric-title">🌧️ DỰ BÁO LƯỢNG MƯA</div>
                <div class="metric-value" style="color: #60a5fa;">{rain_sum} mm</div>
                <div class="metric-sub">Khu vực TP.HCM</div>
            </div>
            """,
          unsafe_allow_html=True,
      )

    with c4:
      st.markdown(
          f"""
            <div class="metric-card">
                <div class="metric-title">☔ XÁC SUẤT MƯA</div>
                <div class="metric-value" style="color: #a78bfa;">{rain_prob}%</div>
                <div class="metric-sub">Trong ngày hôm nay</div>
            </div>
            """,
          unsafe_allow_html=True,
      )

  else:
    st.error("Không thể phân tích dữ liệu tổng hợp.")
else:
  st.error("Chưa có bản tin thủy văn mới.")