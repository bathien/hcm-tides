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

# KHAI BÁO MODEL GEMINI FLASH CHUẨN THẾ HỆ MỚI NHẤT
MODEL_NAME = "gemini-2.5-flash"

# 1. CẤU HÌNH GIAO DIỆN TỐI ƯU MÀN HÌNH TV 43 INCH
st.set_page_config(
    page_title="CẢNH BÁO NGẬP & WFH THẢO ĐIỀN",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# THAY THẾ AUTORUN BẰNG JAVASCRIPT NHÚNG: TỰ ĐỘNG RELOAD MỖI 60 GIÂY (60000ms)
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

# CSS TỰ ĐỘNG PHÓNG TO CHỮ & THEME TƯƠNG PHẢN CAO DÀNH CHO TV 43 INCH
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
        .wfh-card-weekend {
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            border: 3px solid #64748b;
            border-radius: 16px;
            padding: 25px;
            color: #94a3b8;
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


# 2. XÓA CACHE TỰ ĐỘNG LÚC 11:00 SÁNG GIỜ VIỆT NAM (UTC+7)
def check_clear_cache():
  now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  if now_vn.hour == 11 and now_vn.minute in [0, 1, 2]:
    st.cache_data.clear()


check_clear_cache()


# 3. LẤY DỰ BÁO LƯỢNG MƯA DÀNH RIÊNG CHO THẢO ĐIỀN (10.8031, 106.7324)
@st.cache_data(ttl=3600)
def fetch_weather_thao_dien(target_date):
  url = f"https://api.open-meteo.com/v1/forecast?latitude=10.8031&longitude=106.7324&daily=precipitation_sum,precipitation_probability_max&timezone=Asia%2FBangkok&start_date={target_date}&end_date={target_date}"
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
def fetch_pdf_for_date(target_date):
  pdf_url = build_pdf_url(target_date)
  try:
    res = requests.get(pdf_url, headers=HEADERS, timeout=5, verify=False)
    if res.status_code == 200 and len(res.content) > 1000:
      return pdf_url, res.content
  except Exception:
    pass
  return None, None


# 4. PHÂN TÍCH VÀ ĐỀ XUẤT WFH DÀNH RIÊNG CHO THẢO ĐIỀN BẰNG GEMINI FLASH
def analyze_thao_dien_wfh(pdf_bytes, rain_sum, rain_prob, target_date_str):
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
        Bạn là hệ thống trí tuệ nhân tạo chuyên đánh giá rủi ro ngập lụt cho khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM).
        Hãy đọc tệp PDF thủy văn TP.HCM cho ngày {target_date_str} và dữ liệu mưa thực tế tại tọa độ Thảo Điền (10.8031, 106.7324):
        - Lượng mưa dự báo tại Thảo Điền: {rain_sum} mm.
        - Xác suất mưa: {rain_prob} %.

        Đặc thù Thảo Điền: Là vùng ven sông Sài Gòn, chịu ảnh hưởng rất lớn từ trạm thủy văn Phú An. 
        Nếu Triều cường Phú An >= 1.60m (Báo động 3) hoặc (>= 1.50m Báo động 2 + Mưa > 15mm), đường Quốc Hương, Nguyễn Văn Hưởng... tại Thảo Điền sẽ bị ngập rất sâu.

        Nhiệm vụ:
        1. Trích xuất số liệu TRẠM PHÚ AN (Mực nước đỉnh triều, Giờ đỉnh triều, Cấp báo động).
        2. Khuyến nghị chế độ làm việc:
           - "KHUYÊN NÊN WFH (LÀM VIỆC TẠI NHÀ)": Nguy cơ ngập cao tại Thảo Điền.
           - "CÂN NHẮC WFH / ĐI LẠI TRÁNH GIỜ CAO ĐIỂM": Nguy cơ ngập vừa/nhẹ.
           - "ĐẾN VĂN PHÒNG BÌNH THƯỜNG": An toàn, không ngập.

        Trả về kết quả ĐÚNG định dạng JSON:
        {{
            "dinh_trieu": "1.68m",
            "gio_dinh_trieu": "17h30",
            "bao_dong": "BD3",
            "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)",
            "muc_do_wfh": "DANGER",
            "ly_do_wfh": "Cảnh báo ngập sâu các tuyến đường ven sông tại Thảo Điền (Quốc Hương, Nguyễn Văn Hưởng) do đỉnh triều BD3 kết hợp mưa."
        }}
        Lưu ý: "muc_do_wfh" chỉ nhận: "DANGER", "WARNING", hoặc "SAFE".
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
is_weekend = today_date.weekday() >= 5  # Thứ 7 & Chủ Nhật

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
  st.markdown(
      "<h1 style='font-size: 38px; color: #38bdf8; margin:0;'>🚨 HỆ THỐNG CẢNH"
      " BÁO NGẬP & WFH KHU VỰC THẢO ĐIỀN</h1>",
      unsafe_allow_html=True,
  )
with col_h2:
  st.markdown(
      f"<div style='text-align: right; font-size: 22px; color: #94a3b8;'>🕒"
      f" {now_vn.strftime('%H:%M:%S')} | 📅 {now_vn.strftime('%d/%m/%Y')}</div>",
      unsafe_allow_html=True,
  )

st.markdown("---")

if is_weekend:
  st.markdown(
      """
        <div class="wfh-card-weekend">
            <div style="font-size: 24px; text-transform: uppercase;">THÔNG BÁO CUỐI TUẦN:</div>
            <div style="font-size: 48px; font-weight: 900; margin: 10px 0;">☕ HÔM NAY LÀ NGÀY NGHỈ CUỐI TUẦN</div>
            <div style="font-size: 24px;">Hệ thống tạm ngắt khuyến nghị WFH. Chúc bạn có kỳ nghỉ cuối tuần vui vẻ!</div>
        </div>
        """,
      unsafe_allow_html=True,
  )
else:
  target_date = today_date
  target_date_str = target_date.strftime("%Y-%m-%d")

  with st.spinner(
      "Đang tổng hợp dữ liệu Thủy văn & Mưa tọa độ Thảo Điền cho ngày"
      f" {target_date.strftime('%d/%m/%Y')}..."
  ):
    pdf_url, pdf_bytes = fetch_pdf_for_date(target_date)
    rain_sum, rain_prob = fetch_weather_thao_dien(target_date_str)

  if pdf_url and pdf_bytes:
    data = analyze_thao_dien_wfh(
        pdf_bytes, rain_sum, rain_prob, target_date.strftime("%d/%m/%Y")
    )

    if data:
      wfh_style = "wfh-card-safe"
      wfh_icon = "✅"
      if data.get("muc_do_wfh") == "DANGER":
        wfh_style = "wfh-card-danger"
        wfh_icon = "🚨"
      elif data.get("muc_do_wfh") == "WARNING":
        wfh_style = "wfh-card-warning"
        wfh_icon = "⚠️"

      # 1. THẺ KHUYẾN NGHỊ WFH TRÊN TV
      st.markdown(
          f"""
            <div class="{wfh_style}">
                <div style="font-size: 22px; text-transform: uppercase; letter-spacing: 2px;">KHUYẾN NGHỊ LÀM VIỆC TẠI THẢO ĐIỀN ({target_date.strftime('%d/%m/%Y')}):</div>
                <div style="font-size: 46px; font-weight: 900; margin: 8px 0;">{wfh_icon} {data.get('khuyen_nghi_wfh', 'N/A')}</div>
                <div style="font-size: 24px; line-height: 1.4;">👉 <b>Cảnh báo khu vực:</b> {data.get('ly_do_wfh', 'N/A')}</div>
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
                    <div class="metric-sub">Trạm Phú An</div>
                </div>
                """,
            unsafe_allow_html=True,
        )

      with c3:
        st.markdown(
            f"""
                <div class="metric-card">
                    <div class="metric-title">🌧️ MƯA TẠI THẢO ĐIỀN</div>
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
      st.error("Không thể phân tích dữ liệu ngày hôm nay.")
  else:
    st.info(
        f"ℹ️ Chưa có bản tin thủy văn được phát hành cho ngày hôm nay"
        f" ({target_date.strftime('%d/%m/%Y')}). Bản tin thường cập nhật"
        " lúc 11:00 AM."
    )