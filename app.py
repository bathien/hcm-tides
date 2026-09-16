import datetime
import io
import requests
import streamlit as st
import urllib3
from google import genai
from google.genai import types

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="Thủy Văn Phú An - AI Secrets", page_icon="🤖", layout="wide"
)

st.title("🤖 Dự Báo Thủy Văn Trạm Phú An (Gemini AI)")
st.caption("Ứng dụng tự động đọc tệp PDF bản tin và trích xuất số liệu mực nước")

# Truy xuất Gemini API Key từ Secrets của Streamlit
try:
  GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
  st.error(
      "❌ Chưa cấu hình `GEMINI_API_KEY` trong Secrets. Vui lòng kiểm tra lại"
      " Cài đặt trên Streamlit Cloud hoặc tệp `.streamlit/secrets.toml`."
  )
  st.stop()

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


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


def analyze_phu_an_with_ai(pdf_bytes):
  """Khởi tạo Client và gửi PDF sang Gemini API"""
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = """
        Bạn là chuyên gia phân tích dữ liệu thủy văn. Hãy đọc tệp PDF này và trích xuất dữ liệu:
        1. Tìm toàn bộ thông tin dự báo liên quan tới TRẠM PHÚ AN (Sông Sài Gòn).
        2. Tổng hợp các thông số chính:
           - Mực nước đỉnh triều cao nhất (m) và Giờ xuất hiện.
           - Mực nước chân triều thấp nhất (m) và Giờ xuất hiện.
           - Cấp báo động triều cường (BD1, BD2, BD3 nếu có).
        3. Định dạng đầu ra bằng Markdown sạch đẹp, có Bảng tóm tắt số liệu rõ ràng.
        """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(
                data=pdf_bytes,
                mime_type="application/pdf",
            ),
            prompt,
        ],
    )
    return response.text
  except Exception as e:
    return f"❌ Lỗi xử lý AI: {e}"


# --- GIAO DIỆN CHÍNH ---
with st.spinner("Đang tìm bản tin thủy văn mới nhất..."):
  pdf_url, latest_date, pdf_bytes = fetch_latest_pdf()

if pdf_url and latest_date:
  st.success(f"📅 **Ngày bản tin:** {latest_date.strftime('%d/%m/%Y')}")
  st.markdown(f"🔗 [Mở tệp PDF gốc]({pdf_url})")
  st.markdown("---")

  with st.spinner("🤖 AI đang phân tích dữ liệu trạm Phú An..."):
    ai_analysis = analyze_phu_an_with_ai(pdf_bytes)

  st.subheader("📊 Số liệu trích xuất tự động (Trạm Phú An)")
  st.markdown(ai_analysis)

else:
  st.error("Không tìm thấy tệp PDF dự báo nào trong 7 ngày gần đây.")