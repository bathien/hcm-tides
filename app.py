import io
import re
import pandas as pd
import pdfplumber
import requests
import streamlit as st
import urllib3
from bs4 import BeautifulSoup

# Tắt cảnh báo kết nối SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="Theo Dõi Thủy Văn TP.HCM (Có Debug)", page_icon="🌊", layout="wide"
)

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM Hằng Ngày")
st.caption("Nguồn dữ liệu: phongchonglutbaotphcm.gov.vn")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


@st.cache_data(ttl=600)
def fetch_phoca_data_with_debug():
  """Hàm bóc tách dữ liệu có ghi lại log Debug chi tiết"""
  debug_log = []
  results = []

  try:
    debug_log.append(f"🌐 1. Gửi request tới: `{TARGET_URL}`")
    res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"

    debug_log.append(f"📡 Mã phản hồi (Status Code): `{res.status_code}`")

    if res.status_code == 200:
      soup = BeautifulSoup(res.text, "html.parser")
      all_a_tags = soup.find_all("a", href=True)
      debug_log.append(
          f"🔍 Tìm thấy tổng cộng `{len(all_a_tags)}` thẻ `<a>` (link) trên trang web."
      )

      # Quét các thẻ <a> chứa liên kết PDF/PhocaDownload
      for a in all_a_tags:
        title = a.get_text(strip=True)
        href = a["href"]

        if any(
            k in href.lower()
            for k in ["phocadownload", "download", "preview", ".pdf"]
        ):
          match = re.search(r"window\.open\('([^']+)'", href)
          clean_url = match.group(1) if match else href

          if not clean_url.startswith("http"):
            clean_url = BASE_DOMAIN + clean_url

          display_title = title if len(title) > 5 else clean_url.split("/")[-1]
          results.append({"title": display_title, "link": clean_url})

      debug_log.append(
          f"🎯 Đã lọc được `{len(results)}` liên kết bản tin PDF/PhocaDownload."
      )

  except Exception as e:
    debug_log.append(f"❌ Lỗi kết nối: `{str(e)}`")

  return results, debug_log


def parse_pdf_with_debug(pdf_url):
  """Đọc file PDF và ghi log Debug"""
  pdf_debug_log = []
  try:
    pdf_debug_log.append(f"📥 Đang tải file PDF từ: `{pdf_url}`")
    res = requests.get(pdf_url, headers=HEADERS, timeout=15, verify=False)
    pdf_debug_log.append(
        f"📡 Trạng thái tải file PDF: `{res.status_code}` (Dung lượng:"
        f" {len(res.content)} bytes)"
    )

    pdf_file = io.BytesIO(res.content)
    text_content = ""
    tables_data = []

    with pdfplumber.open(pdf_file) as pdf:
      pdf_debug_log.append(f"📄 Tổng số trang PDF: `{len(pdf.pages)}`")
      for i, page in enumerate(pdf.pages):
        text = page.extract_text()
        if text:
          text_content += text + "\n"

        extracted_tb = page.extract_tables()
        if extracted_tb:
          pdf_debug_log.append(
              f"📊 Trang {i+1}: Tìm thấy `{len(extracted_tb)}` bảng số liệu."
          )
          for t in extracted_tb:
            tables_data.append(pd.DataFrame(t))

    return text_content, tables_data, pdf_debug_log
  except Exception as e:
    pdf_debug_log.append(f"❌ Lỗi xử lý PDF: `{str(e)}`")
    return f"Lỗi: {e}", [], pdf_debug_log


# --- GIAO DIỆN HỂN THỊ CHÍNH ---
with st.spinner("Đang kết nối tới trang thủy văn..."):
  hydro_items, fetch_logs = fetch_phoca_data_with_debug()

# 🛠️ KHU VỰC DEBUG KẾT NỐI
with st.expander("🛠️ BẬT / TẮT NHẬT KÝ DEBUG (Kiểm tra lỗi cào web)"):
  st.subheader("Nhật ký lấy danh sách bản tin:")
  for log in fetch_logs:
    st.write(log)

  if hydro_items:
    st.subheader("Danh sách URL cào được:")
    st.json(hydro_items)

st.markdown("---")

if hydro_items:
  df_items = pd.DataFrame(hydro_items).drop_duplicates(subset=["link"])
  unique_items = df_items.to_dict("records")

  selected_title = st.selectbox(
      "📅 Chọn bản tin thủy văn bạn muốn xem:",
      options=[item["title"] for item in unique_items],
  )

  selected_item = next(
      item for item in unique_items if item["title"] == selected_title
  )
  pdf_url = selected_item["link"]

  st.markdown(f"📥 **Đường dẫn tệp gốc:** [{pdf_url}]({pdf_url})")

  with st.spinner("Đang đọc các bảng số liệu từ PDF..."):
    pdf_text, pdf_tables, pdf_logs = parse_pdf_with_debug(pdf_url)

  # 🛠️ KHU VỰC DEBUG XỬ LÝ PDF
  with st.expander("🛠️ NHẬT KÝ DEBUG XỬ LÝ PDF"):
    for log in pdf_logs:
      st.write(log)

  if pdf_tables:
    st.subheader("📊 Bảng thông số mực nước / Đỉnh triều trích xuất")
    for df_tb in pdf_tables:
      df_tb.columns = df_tb.iloc[0]
      clean_df = df_tb[1:].reset_index(drop=True)
      st.dataframe(clean_df, use_container_width=True)
  else:
    st.info("ℹ️ Không tìm thấy dạng bảng kẻ sẵn trong PDF này.")

  st.subheader("📝 Văn bản chi tiết trong bản tin")
  st.text_area("Toàn văn bản tin:", pdf_text, height=350)

else:
  st.error(
      "Không thể lấy được dữ liệu bản tin. Vui lòng mở mục '🛠️ BẬT / TẮT NHẬT"
      " KÝ DEBUG' ở trên để xem nguyên nhân."
  )