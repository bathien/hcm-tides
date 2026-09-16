import datetime
import io
import re
import pandas as pd
import pdfplumber
import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="Thủy Văn TP.HCM Mới Nhất", page_icon="🌊", layout="wide"
)

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM Hằng Ngày")
st.caption("Tự động tải bản tin thủy văn mới nhất từ Ban Chỉ huy PCTT TP.HCM")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def build_pdf_url(target_date):
  """Tạo URL theo cấu trúc phocadownload/YYYY/MM-YYYY/HCMC_TVHN_YYYYMMDD.pdf"""
  yyyy = target_date.strftime("%Y")
  mm = target_date.strftime("%m")
  dd = target_date.strftime("%d")
  pdf_path = f"phocadownload/{yyyy}/{mm}-{yyyy}/HCMC_TVHN_{yyyy}{mm}{dd}.pdf"
  return f"{BASE_DOMAIN}/{pdf_path}"


@st.cache_data(ttl=1800)
def fetch_latest_pdf():
  """Tự động tìm file PDF bản tin gần nhất (lùi tối đa 7 ngày từ hôm nay)"""
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


def parse_pdf_bytes(pdf_bytes):
  """Đọc dữ liệu từ byte file PDF"""
  pdf_file = io.BytesIO(pdf_bytes)
  text_out = ""
  tables_out = []

  with pdfplumber.open(pdf_file) as pdf:
    for page in pdf.pages:
      txt = page.extract_text()
      if txt:
        text_out += txt + "\n"

      extracted_tb = page.extract_tables()
      for tb in extracted_tb:
        df_tb = pd.DataFrame(tb).dropna(how="all")
        if len(df_tb) > 1:
          tables_out.append(df_tb)

  # Nếu không nhận diện được khung kẻ, tự bóc tách Raw Text thành dòng
  if not tables_out and text_out:
    rows = []
    for line in text_out.split("\n"):
      if any(
          t in line.lower()
          for t in [
              "phú an",
              "nhà bè",
              "thủ dầu một",
              "báo động",
              "mực nước",
              "đỉnh triều",
          ]
      ) or re.search(r"\d{1,2}h\d{0,2}|\d+,\d+|\d+\.\d+", line):
        parts = [p.strip() for p in re.split(r"\s{2,}|\t", line) if p.strip()]
        if len(parts) > 1:
          rows.append(parts)

    if rows:
      tables_out.append(pd.DataFrame(rows))

  return text_out, tables_out


# --- GIAO DIỆN HỂN THỊ STREAMLIT ---
with st.spinner("Đang kiểm tra và tải bản tin thủy văn mới nhất..."):
  pdf_url, latest_date, pdf_bytes = fetch_latest_pdf()

if pdf_url and latest_date:
  st.success(
      f"📅 **Bản tin mới nhất ngày:** {latest_date.strftime('%d/%m/%Y')}"
  )
  st.markdown(f"🔗 **Đường dẫn tệp gốc:** [{pdf_url}]({pdf_url})")
  st.markdown("---")

  pdf_text, pdf_tables = parse_pdf_bytes(pdf_bytes)

  if pdf_tables:
    st.subheader("📊 Bảng thông số mực nước / Đỉnh triều trích xuất từ PDF")
    for df_tb in pdf_tables:
      st.dataframe(df_tb, use_container_width=True)

  st.subheader("📝 Văn bản chi tiết bản tin")
  st.text_area("Toàn văn bản tin:", pdf_text, height=350)

else:
  st.error(
      "Không tìm thấy bản tin thủy văn nào trong 7 ngày gần đây hoặc kết nối"
      " tới máy chủ bị gián đoạn."
  )