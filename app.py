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

MODEL_NAME = "gemini-3.6-flash"

# 1. CẤU HÌNH GIAO DIỆN MÀN HÌNH TV 43 INCH
st.set_page_config(
    page_title="CẢNH BÁO NGẬP & WFH BANQUP HCM",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# TỰ ĐỘNG RELOAD MÀN HÌNH MỖI 60 GIÂY
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

# CSS GIAO DIỆN MÀN HÌNH TV & STYLE NÚT MANUAL REQUEST
st.markdown(
    """
    <style>
        html, body, [class*="css"] { font-size: 19px !important; }
        .day-container {
            background-color: #0f172a;
            border-radius: 20px;
            padding: 20px;
            border: 2px solid #1e293b;
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
        }
        .metric-card-mini {
            background-color: #1e293b;
            border-radius: 12px;
            padding: 12px;
            text-align: center;
            border: 1px solid #334155;
            margin-bottom: 10px;
        }
        .metric-title-mini { font-size: 16px; color: #94a3b8; font-weight: 600; }
        .metric-value-mini { font-size: 32px; font-weight: 900; color: #38bdf8; }
        .metric-sub-mini { font-size: 16px; color: #f1f5f9; }
        .wfh-card-danger {
            background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%);
            border: 2px solid #ef4444; border-radius: 14px; padding: 16px; color: white; margin-bottom: 15px;
        }
        .wfh-card-warning {
            background: linear-gradient(135deg, #713f12 0%, #854d0e 100%);
            border: 2px solid #eab308; border-radius: 14px; padding: 16px; color: white; margin-bottom: 15px;
        }
        .wfh-card-safe {
            background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
            border: 2px solid #10b981; border-radius: 14px; padding: 16px; color: white; margin-bottom: 15px;
        }
        .wfh-card-weekend {
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            border: 2px solid #64748b; border-radius: 14px; padding: 16px; color: #94a3b8; margin-bottom: 15px;
        }
        
        div.stButton > button {
            width: 100%;
            font-size: 18px !important;
            font-weight: bold !important;
            background-color: #0284c7 !important;
            color: white !important;
            border-radius: 12px !important;
            padding: 10px !important;
            border: none !important;
        }
        div.stButton > button:hover {
            background-color: #0369a1 !important;
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

# KIỂM TRA SECRETS
try:
  GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
  ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]
except KeyError as e:
  st.error(f"⚠️ Chưa cấu hình {e} trong Secrets.")
  st.stop()


# HỘP THOẠI XÁC THỰC MẬT KHẨU KHI BẤM CLEAR CACHE
@st.dialog("🔑 BẢO MẬT: XÁC NHẬN LÀM MỚI CACHE")
def request_clear_cache_dialog():
  st.write("Vui lòng nhập mật khẩu quản trị viên để làm mới dữ liệu từ máy chủ:")
  pwd_input = st.text_input("Mật khẩu:", type="password")

  if st.button("Xác nhận làm mới"):
    if pwd_input == ADMIN_PASSWORD:
      st.cache_data.clear()
      st.success("✅ Đã xóa Cache thành công! Đang tải lại dữ liệu...")
      st.rerun()
    else:
      st.error("❌ Mật khẩu không chính xác. Vui lòng thử lại!")


def get_next_working_day(from_date):
  current_w = from_date.weekday()
  if current_w < 4:
    return from_date + datetime.timedelta(days=1)
  elif current_w == 4:
    return from_date + datetime.timedelta(days=3)
  elif current_w == 5:
    return from_date + datetime.timedelta(days=2)
  else:
    return from_date + datetime.timedelta(days=1)


# CACHE 1 NGÀY (24h = 86400 giây): DỰ BÁO MƯA THẢO ĐIỀN
@st.cache_data(ttl=86400)
def fetch_weather_thao_dien(target_date_str):
  url = f"https://api.open-meteo.com/v1/forecast?latitude=10.8031&longitude=106.7324&daily=precipitation_sum,precipitation_probability_max&timezone=Asia%2FBangkok&start_date={target_date_str}&end_date={target_date_str}"
  fetch_time = (
      datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  ).strftime("%H:%M:%S")
  try:
    res = requests.get(url, timeout=5)
    if res.status_code == 200:
      data = res.json()
      rain_sum = data["daily"]["precipitation_sum"][0]
      rain_prob = data["daily"]["precipitation_probability_max"][0]
      return rain_sum, rain_prob, fetch_time
  except Exception:
    pass
  return 0, 0, fetch_time


def build_pdf_url(target_date):
  yyyy = target_date.strftime("%Y")
  mm = target_date.strftime("%m")
  dd = target_date.strftime("%d")
  return f"{BASE_DOMAIN}/phocadownload/{yyyy}/{mm}-{yyyy}/HCMC_TVHN_{yyyy}{mm}{dd}.pdf"


# CACHE 1 NGÀY (24h = 86400 giây): FILE PDF THỦY VĂN
@st.cache_data(ttl=86400)
def fetch_latest_pdf(today_date):
  fetch_time = (
      datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  ).strftime("%H:%M:%S")
  for i in range(5):
    check_date = today_date - datetime.timedelta(days=i)
    pdf_url = build_pdf_url(check_date)
    try:
      res = requests.get(pdf_url, headers=HEADERS, timeout=5, verify=False)
      if res.status_code == 200 and len(res.content) > 1000:
        return pdf_url, check_date, res.content, fetch_time
    except Exception:
      continue
  return None, None, None, fetch_time


# CACHE 1 NGÀY (24h = 86400 giây): PHÂN TÍCH GEMINI AI
@st.cache_data(ttl=86400)
def analyze_workdays_wfh_cached(
    pdf_bytes,
    today_date_str,
    next_workday_str,
    pdf_date_str,
    r_sum_today,
    r_prob_today,
    r_sum_next,
    r_prob_next,
):
  ai_call_time = (
      datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  ).strftime("%H:%M:%S")
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
        Bạn là hệ thống AI đánh giá rủi ro ngập lụt khu vực THẢO ĐIỀN (TP. Thủ Đức, TP.HCM).
        Tệp PDF thủy văn phát hành ngày {pdf_date_str}. 
        Hãy phân tích dữ liệu cho 2 mốc thời gian:
        1. Hôm nay ({today_date_str}): Mưa dự báo {r_sum_today}mm, Xác suất {r_prob_today}%.
        2. Next Working Day ({next_workday_str}): Mưa dự báo {r_sum_next}mm, Xác suất {r_prob_next}%.

        Đặc thù Thảo Điền: Ven sông Sài Gòn, ngập sâu khi Triều cường Phú An >= 1.60m (BD3) hoặc (>= 1.50m BD2 + Mưa > 15mm).

        Nhiệm vụ: Trích xuất thông số trạm PHÚ AN và đưa ra khuyến nghị WFH cho từng ngày.

        Trả về ĐÚNG ĐỊNH DẠNG JSON MẢNG (Không thêm văn bản ngoài):
        [
            {{
                "ngay": "{today_date_str}",
                "label": "HÔM NAY",
                "dinh_trieu": "1.68m",
                "gio_dinh_trieu": "17h30",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)",
                "muc_do_wfh": "DANGER",
                "ly_do_wfh": "Cảnh báo ngập sâu do đỉnh triều BD3 kết hợp nguy cơ mưa."
            }},
            {{
                "ngay": "{next_workday_str}",
                "label": "NEXT WORKING DAY",
                "dinh_trieu": "1.62m",
                "gio_dinh_trieu": "18h10",
                "bao_dong": "BD3",
                "khuyen_nghi_wfh": "CÂN NHẮC WFH",
                "muc_do_wfh": "WARNING",
                "ly_do_wfh": "Đỉnh triều cao xấp xỉ BD3 vào giờ tan tầm."
            }}
        ]
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
    return json.loads(clean_json), ai_call_time
  except Exception:
    return None, ai_call_time


# --- GIAO DIỆN MÀN HÌNH CHÍNH ---
now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
today_date = now_vn.date()
next_workday = get_next_working_day(today_date)

col_h1, col_h2, col_h3 = st.columns([3, 1, 1])
with col_h1:
  st.markdown(
      "<h1 style='font-size: 36px; color: #38bdf8; margin:0;'>🚨 CẢNH BÁO NGẬP"
      " & WFH BANQUP HCM</h1>",
      unsafe_allow_html=True,
  )
with col_h2:
  st.markdown(
      f"<div style='text-align: right; font-size: 20px; color: #94a3b8;'>🕒"
      f" {now_vn.strftime('%H:%M:%S')}<br>📅 {now_vn.strftime('%d/%m/%Y')}</div>",
      unsafe_allow_html=True,
  )

with col_h3:
  # BẤM NÚT SẼ MỞ HỘP THOẠI YÊU CẦU MẬT KHẨU
  if st.button("🔄 Làm mới dữ liệu ngay"):
    request_clear_cache_dialog()

st.markdown("---")

with st.spinner("Đang lấy dữ liệu thủy văn & thời tiết..."):
  pdf_url, pdf_date, pdf_bytes, pdf_fetch_time = fetch_latest_pdf(today_date)

  r_sum_today, r_prob_today, weather_fetch_time = fetch_weather_thao_dien(
      today_date.strftime("%Y-%m-%d")
  )
  r_sum_next, r_prob_next, _ = fetch_weather_thao_dien(
      next_workday.strftime("%Y-%m-%d")
  )

if pdf_bytes:
  two_days_data, ai_call_time = analyze_workdays_wfh_cached(
      pdf_bytes,
      today_date.strftime("%d/%m/%Y"),
      next_workday.strftime("%d/%m/%Y"),
      pdf_date.strftime("%d/%m/%Y"),
      r_sum_today,
      r_prob_today,
      r_sum_next,
      r_prob_next,
  )

  if two_days_data and len(two_days_data) >= 2:
    col_today, col_next = st.columns(2)

    days_list = [
        {"data": two_days_data[0], "date_obj": today_date, "col": col_today},
        {"data": two_days_data[1], "date_obj": next_workday, "col": col_next},
    ]

    for item_info in days_list:
      item = item_info["data"]
      d_obj = item_info["date_obj"]
      col = item_info["col"]
      is_wknd = d_obj.weekday() >= 5

      r_sum, r_prob, _ = fetch_weather_thao_dien(d_obj.strftime("%Y-%m-%d"))

      with col:
        st.markdown('<div class="day-container">', unsafe_allow_html=True)
        st.markdown(
            f"<h2 style='color: #f8fafc; margin-top:0; text-align:center;'>📌"
            f" {item.get('label', '')} ({item.get('ngay', '')})</h2>",
            unsafe_allow_html=True,
        )

        if is_wknd:
          st.markdown(
              """
                        <div class="wfh-card-weekend">
                            <div style="font-size: 20px; font-weight: bold;">☕ NGHỈ CUỐI TUẦN</div>
                            <div style="font-size: 18px; margin-top:5px;">Hệ thống không áp dụng đề xuất WFH.</div>
                        </div>
                        """,
              unsafe_allow_html=True,
          )
        else:
          wfh_style = "wfh-card-safe"
          wfh_icon = "✅"
          if item.get("muc_do_wfh") == "DANGER":
            wfh_style = "wfh-card-danger"
            wfh_icon = "🚨"
          elif item.get("muc_do_wfh") == "WARNING":
            wfh_style = "wfh-card-warning"
            wfh_icon = "⚠️"

          st.markdown(
              f"""
                        <div class="{wfh_style}">
                            <div style="font-size: 18px; text-transform: uppercase;">KHUYẾN NGHỊ LÀM VIỆC:</div>
                            <div style="font-size: 32px; font-weight: 900; margin: 5px 0;">{wfh_icon} {item.get('khuyen_nghi_wfh', 'N/A')}</div>
                            <div style="font-size: 18px;">👉 {item.get('ly_do_wfh', 'N/A')}</div>
                        </div>
                        """,
              unsafe_allow_html=True,
          )

        mc1, mc2 = st.columns(2)
        with mc1:
          st.markdown(
              f"""<div class="metric-card-mini">
                  <div class="metric-title-mini">🌊 ĐỈNH TRIỀU PHÚ AN</div>
                  <div class="metric-value-mini">{item.get('dinh_trieu', 'N/A')}</div>
                  <div class="metric-sub-mini">⏰ Giờ: <b>{item.get('gio_dinh_trieu', 'N/A')}</b></div>
              </div>""",
              unsafe_allow_html=True,
          )
          st.markdown(
              f"""<div class="metric-card-mini">
                  <div class="metric-title-mini">🌧️ MƯA THẢO ĐIỀN</div>
                  <div class="metric-value-mini" style="color: #60a5fa;">{r_sum} mm</div>
                  <div class="metric-sub-mini">Lượng mưa dự báo</div>
              </div>""",
              unsafe_allow_html=True,
          )

        with mc2:
          st.markdown(
              f"""<div class="metric-card-mini">
                  <div class="metric-title-mini">🚨 CẤP BÁO ĐỘNG</div>
                  <div class="metric-value-mini" style="color: #ef4444;">{item.get('bao_dong', 'N/A')}</div>
                  <div class="metric-sub-mini">Trạm Phú An</div>
              </div>""",
              unsafe_allow_html=True,
          )
          st.markdown(
              f"""<div class="metric-card-mini">
                  <div class="metric-title-mini">☔ XÁC SUẤT MƯA</div>
                  <div class="metric-value-mini" style="color: #a78bfa;">{r_prob}%</div>
                  <div class="metric-sub-mini">Trong ngày</div>
              </div>""",
              unsafe_allow_html=True,
          )

        st.markdown("</div>", unsafe_allow_html=True)
  else:
    st.error("Không thể bóc tách dữ liệu cho 2 ngày.")
else:
  st.error("Không tìm thấy tệp PDF dự báo thủy văn nào.")

# BẢNG LOG THÔNG TIN CACHE
with st.expander("ℹ️ TRẠNG THÁI CACHE (TỰ ĐỘNG LƯU RAM 24 GIỜ)"):
  st.write(
      f"- 🤖 **Gemini AI Call:** `{ai_call_time}` | 📄 **PDF Data:**"
      f" `{pdf_fetch_time}` | 🌤️ **Weather Data:** `{weather_fetch_time}`"
  )
  st.write(
      "- Dữ liệu tự động lưu đệm 24 tiếng. Nhấn nút **'🔄 Làm mới dữ liệu ngay'**"
      " và nhập Mật khẩu bảo mật để xóa Cache."
  )