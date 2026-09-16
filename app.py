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

st.set_page_config(
    page_title="DỰ BÁO NGẬP & WFH THẢO ĐIỀN THEO TUẦN",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Tự động reload mỗi 60 giây
st.components.v1.html(
    """
    <script>
        setTimeout(function(){
            window.parent.location.reload();
        }, 60000);
    </script>
""",
    height=0,
)

# CSS TỐI ƯU GIAO DIỆN MÀN HÌNH TV 43 INCH
st.markdown(
    """
    <style>
        html, body, [class*="css"] { font-size: 20px !important; }
        .metric-card {
            background-color: #1e293b;
            border-radius: 14px;
            padding: 16px;
            text-align: center;
            border: 2px solid #334155;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
        }
        .metric-title { font-size: 18px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; }
        .metric-value { font-size: 40px; font-weight: 900; color: #38bdf8; }
        .metric-sub { font-size: 18px; color: #f1f5f9; margin-top: 6px; }
        
        .wfh-card-danger {
            background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
            border: 3px solid #ef4444;
            border-radius: 16px;
            padding: 20px;
            color: white;
        }
        .wfh-card-warning {
            background: linear-gradient(135deg, #713f12 0%, #854d0e 100%);
            border: 3px solid #eab308;
            border-radius: 16px;
            padding: 20px;
            color: white;
        }
        .wfh-card-safe {
            background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
            border: 3px solid #10b981;
            border-radius: 16px;
            padding: 20px;
            color: white;
        }
        .wfh-card-weekend {
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            border: 3px solid #64748b;
            border-radius: 16px;
            padding: 20px;
            color: #94a3b8;
        }
        /* Custom style cho Tabs */
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] {
            font-size: 22px !important;
            font-weight: bold;
            padding: 12px 24px;
            background-color: #1e293b;
            border-radius: 10px;
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


def check_clear_cache():
  now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  if now_vn.hour == 11 and now_vn.minute in [0, 1, 2]:
    st.cache_data.clear()


check_clear_cache()


# LẤY DỰ BÁO LƯỢNG MƯA THẢO ĐIỀN THEO NGÀY CỤ THỂ
@st.cache_data(ttl=3600)
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


@st.cache_data(ttl=1800)
def fetch_latest_available_pdf(today_date):
  """Lấy bản tin mới nhất có sẵn trên server"""
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


# HÀM TÍNH DANH SÁCH CÁC NGÀY LÀM VIỆC CÒN LẠI TRONG TUẦN
def get_remaining_workdays(today_date):
  workdays = []
  current_weekday = today_date.weekday()  # 0: T2, 1: T3, ..., 4: T6, 5: T7, 6: CN

  if current_weekday >= 5:
    # Nếu là cuối tuần, lấy từ Thứ 2 đến Thứ 6 tuần tới
    days_until_monday = 7 - current_weekday
    next_monday = today_date + datetime.timedelta(days=days_until_monday)
    for i in range(5):
      workdays.append(next_monday + datetime.timedelta(days=i))
  else:
    # Nếu là ngày trong tuần, lấy từ hôm nay đến Thứ 6
    days_left = 5 - current_weekday
    for i in range(days_left):
      workdays.append(today_date + datetime.timedelta(days=i))

  return workdays


# AI PHÂN TÍCH VÀ ĐỀ XUẤT WFH THEO CÁC NGÀY LÀM VIỆC
def analyze_week_wfh(pdf_bytes, workdays, latest_pdf_date):
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Chuẩn bị thông tin các ngày làm việc
    dates_info = []
    for d in workdays:
      d_str = d.strftime("%Y-%m-%d")
      rain_sum, rain_prob = fetch_weather_thao_dien(d_str)
      dates_info.append(
          f"- Ngày {d.strftime('%d/%m/%Y')}: Dự báo mưa {rain_sum}mm, Xác"
          f" suất mưa {rain_prob}%."
      )

    prompt = f"""
        Bạn là hệ thống AI đánh giá rủi ro ngập lụt cho khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM).
        Đây là tệp PDF thủy văn phát hành ngày {latest_pdf_date.strftime('%d/%m/%Y')}. 
        Hãy phân tích dữ liệu dự báo cho danh sách CÁC NGÀY LÀM VIỆC CẦN ĐÁNH GIÁ sau:
        {chr(10).join(dates_info)}

        Đặc thù Thảo Điền: Ven sông Sài Gòn, ngập sâu khi Triều cường Phú An >= 1.60m (BD3) hoặc (>= 1.50m BD2 + Mưa > 15mm).

        Nhiệm vụ:
        Trích xuất thông số trạm PHÚ AN và đưa ra khuyến nghị WFH cho TỪNG NGÀY TRONG DANH SÁCH TRÊN.
        
        Trả về kết quả ĐÚNG ĐỊNH DẠNG JSON MẢNG NÀY (Không kèm thêm văn bản ngoài):
        [
            {{
                "ngay": "16/09/2026",
                "thu": "Thứ Tư",
                "dinh_trieu": "1.68m",
                "gio_dinh_trieu": "17h30",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)",
                "muc_do_wfh": "DANGER",
                "ly_do_wfh": "Cảnh báo ngập sâu tại Thảo Điền do đỉnh triều BD3 kết hợp nguy cơ mưa lớn vào giờ tan tầm."
            }}
        ]
        Lưu ý: "muc_do_wfh" chỉ nhận các giá trị: "DANGER", "WARNING", hoặc "SAFE".
        """

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
    )

    clean_json = re.sub(r"```json|```", "", response.text).strip()
    return json.loads(clean_json)
  except Exception:
    return None


# --- GIAO DIỆN MÀN HÌNH TV 43 INCH ---
now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
today_date = now_vn.date()
workdays = get_remaining_workdays(today_date)

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
  st.markdown(
      "<h1 style='font-size: 38px; color: #38bdf8; margin:0;'>🚨 LỊCH CẢNH BÁO"
      " NGẬP & WFH THẢO ĐIỀN THEO TUẦN</h1>",
      unsafe_allow_html=True,
  )
with col_h2:
  st.markdown(
      f"<div style='text-align: right; font-size: 22px; color: #94a3b8;'>🕒"
      f" {now_vn.strftime('%H:%M:%S')} | 📅 {now_vn.strftime('%d/%m/%Y')}</div>",
      unsafe_allow_html=True,
  )

st.markdown("---")

with st.spinner("Đang tải dữ liệu Thủy văn & Phân tích lịch WFH theo tuần..."):
  pdf_url, latest_pdf_date, pdf_bytes = fetch_latest_available_pdf(today_date)

if pdf_bytes:
  week_data = analyze_week_wfh(pdf_bytes, workdays, latest_pdf_date)

  if week_data:
    # TẠO CÁC TABS HÀNG NGÀY CHO CÁC NGÀY LÀM VIỆC
    tab_titles = [
        f"📅 {item.get('thu', '')} ({item.get('ngay', '')})"
        for item in week_data
    ]
    tabs = st.tabs(tab_titles)

    for idx, tab in enumerate(tabs):
      item = week_data[idx]
      d_str = workdays[idx].strftime("%Y-%m-%d")
      rain_sum, rain_prob = fetch_weather_thao_dien(d_str)

      with tab:
        wfh_style = "wfh-card-safe"
        wfh_icon = "✅"
        if item.get("muc_do_wfh") == "DANGER":
          wfh_style = "wfh-card-danger"
          wfh_icon = "🚨"
        elif item.get("muc_do_wfh") == "WARNING":
          wfh_style = "wfh-card-warning"
          wfh_icon = "⚠️"

        # 1. THẺ KHUYẾN NGHỊ WFH THEO NGÀY
        st.markdown(
            f"""
            <div class="{wfh_style}">
                <div style="font-size: 22px; text-transform: uppercase; letter-spacing: 2px;">KHUYẾN NGHỊ LÀM VIỆC ({item.get('thu', '')} - {item.get('ngay', '')}):</div>
                <div style="font-size: 44px; font-weight: 900; margin: 8px 0;">{wfh_icon} {item.get('khuyen_nghi_wfh', 'N/A')}</div>
                <div style="font-size: 22px; line-height: 1.4;">👉 <b>Cảnh báo khu vực Thảo Điền:</b> {item.get('ly_do_wfh', 'N/A')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # 2. BỐN THẺ BÁO CÁO THÔNG SỐ TV
        c1, c2, c3, c4 = st.columns(4)

        with c1:
          st.markdown(
              f"""
                <div class="metric-card">
                    <div class="metric-title">🌊 ĐỈNH TRIỀU PHÚ AN</div>
                    <div class="metric-value">{item.get('dinh_trieu', 'N/A')}</div>
                    <div class="metric-sub">⏰ Đỉnh triều: <b>{item.get('gio_dinh_trieu', 'N/A')}</b></div>
                </div>
                """,
              unsafe_allow_html=True,
          )

        with c2:
          st.markdown(
              f"""
                <div class="metric-card">
                    <div class="metric-title">🚨 CẤP BÁO ĐỘNG</div>
                    <div class="metric-value" style="color: #ef4444;">{item.get('bao_dong', 'N/A')}</div>
                    <div class="metric-sub">Trạm Phú An</div>
                </div>
                """,
              unsafe_allow_html=True,
          )

        with c3:
          st.markdown(
              f"""
                <div class="metric-card">
                    <div class="metric-title">🌧️ MƯA THẢO ĐIỀN</div>
                    <div class="metric-value" style="color: #60a5fa;">{rain_sum} mm</div>
                    <div class="metric-sub">Lượng mưa dự báo</div>
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
                    <div class="metric-sub">Khu vực Thảo Điền</div>
                </div>
                """,
              unsafe_allow_html=True,
          )
  else:
    st.error("Không thể phân tích dữ liệu lịch làm việc theo tuần.")
else:
  st.error("Không tìm thấy tệp PDF dự báo thủy văn nào.")