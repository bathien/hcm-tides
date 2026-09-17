import datetime
import json
import os
import re
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from google import genai
from google.genai import types
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

MODEL_NAME = "gemini-3.6-flash"
BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def get_three_workdays(from_date):
  workdays = []
  current = from_date
  while len(workdays) < 3:
    if current.weekday() < 5:
      workdays.append(current)
    current += datetime.timedelta(days=1)
  return workdays


def fetch_hourly_weather_thao_dien(target_date_str):
  url = f"https://api.open-meteo.com/v1/forecast?latitude=10.8031&longitude=106.7324&hourly=precipitation,precipitation_probability&timezone=Asia%2FBangkok&start_date={target_date_str}&end_date={target_date_str}"
  try:
    res = requests.get(url, timeout=3)
    if res.status_code == 200:
      data = res.json()
      precip = data.get("hourly", {}).get("precipitation", [])
      prob = data.get("hourly", {}).get("precipitation_probability", [])
      return {
          "morning_rain": (
              round(sum(precip[7:10]), 1) if len(precip) >= 10 else 0.0
          ),
          "morning_prob": (
              max(prob[7:10]) if len(prob) >= 10 and prob[7:10] else 0
          ),
          "evening_rain": (
              round(sum(precip[17:20]), 1) if len(precip) >= 20 else 0.0
          ),
          "evening_prob": (
              max(prob[17:20]) if len(prob) >= 20 and prob[17:20] else 0
          ),
      }
  except Exception:
    pass
  return {
      "morning_rain": 0.0,
      "morning_prob": 0,
      "evening_rain": 0.0,
      "evening_prob": 0,
  }


def fetch_latest_pdf(today_date):
  for i in range(5):
    check_date = today_date - datetime.timedelta(days=i)
    pdf_url = f"{BASE_DOMAIN}/phocadownload/{check_date.strftime('%Y')}/{check_date.strftime('%m-%Y')}/HCMC_TVHN_{check_date.strftime('%Y%m%d')}.pdf"
    try:
      res = requests.get(pdf_url, headers=HEADERS, timeout=2, verify=False)
      if res.status_code == 200 and len(res.content) > 1000:
        return check_date, res.content
    except Exception:
      continue
  return None, None


def analyze_three_workdays(pdf_bytes, dates_info_json, pdf_date_str):
  fallback = [
      {
          "ngay": "N/A",
          "label": "HÔM NAY",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "17h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết ổn định.",
      },
      {
          "ngay": "N/A",
          "label": "NEXT WORKDAY 1",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "18h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết ổn định.",
      },
      {
          "ngay": "N/A",
          "label": "NEXT WORKDAY 2",
          "dinh_trieu": "1.55m",
          "gio_dinh_trieu": "19h00",
          "bao_dong": "BD1",
          "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG",
          "muc_do_wfh": "SAFE",
          "ly_do_wfh": "Thời tiết ổn định.",
      },
  ]
  if not pdf_bytes or not GEMINI_API_KEY:
    return fallback
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
        Bạn là chuyên gia phân tích rủi ro ngập lụt khu vực THẢO ĐIỀN (TP. Thủ Đức) cho Banqup VN.
        Tệp PDF phát hành: {pdf_date_str}. Dữ liệu thời tiết: {dates_info_json}
        Trả về ĐÚNG MẢNG JSON 3 PHẦN TỬ (không ký tự xuống dòng trong chuỗi):
        [
            {{"ngay": "DD/MM/YYYY", "label": "HÔM NAY", "dinh_trieu": "1.68m", "gio_dinh_trieu": "17h30", "bao_dong": "BD3", "khuyen_nghi_wfh": "NÊN LÀM VIỆC TẠI NHÀ (WFH)", "muc_do_wfh": "DANGER", "ly_do_wfh": "Triều BD3 kết hợp mưa chiều >30mm gây ngập sâu Nguyễn Văn Hưởng."}},
            {{"ngay": "DD/MM/YYYY", "label": "NEXT WORKDAY 1", "dinh_trieu": "1.62m", "gio_dinh_trieu": "18h10", "bao_dong": "BD3", "khuyen_nghi_wfh": "CÂN NHẮC WFH", "muc_do_wfh": "WARNING", "ly_do_wfh": "Triều BD3 lúc 18h10 nguy cơ ngập nhẹ Quốc Hương."}},
            {{"ngay": "DD/MM/YYYY", "label": "NEXT WORKDAY 2", "dinh_trieu": "1.52m", "gio_dinh_trieu": "19h00", "bao_dong": "BD2", "khuyen_nghi_wfh": "ĐẾN VĂN PHÒNG", "muc_do_wfh": "SAFE", "ly_do_wfh": "Thời tiết thuận lợi cả 2 ca đi lại."}}
        ]
        """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
    )
    json_match = re.search(r"\[.*\]", response.text, re.DOTALL)
    if json_match:
      return json.loads(json_match.group(0), strict=False)
  except Exception:
    pass
  return fallback


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
  now_vn = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
  today_date = now_vn.date()
  three_workdays = get_three_workdays(today_date)

  weather_list = [
      fetch_hourly_weather_thao_dien(d.strftime("%Y-%m-%d"))
      for d in three_workdays
  ]
  pdf_date, pdf_bytes = fetch_latest_pdf(today_date)
  pdf_date_str = (
      pdf_date.strftime("%d/%m/%Y")
      if pdf_date
      else today_date.strftime("%d/%m/%Y")
  )

  ai_data = analyze_three_workdays(
      pdf_bytes, json.dumps(weather_list), pdf_date_str
  )

  cards = []
  for idx in range(3):
    d_obj = three_workdays[idx]
    item = (
        ai_data[idx]
        if idx < len(ai_data) and isinstance(ai_data[idx], dict)
        else {}
    )
    w_data = weather_list[idx]

    muc_do = str(item.get("muc_do_wfh", "SAFE")).upper()
    bg_color = "#065f46"
    icon = "✅"
    if "DANGER" in muc_do:
      bg_color = "#991b1b"
      icon = "🚨"
    elif "WARN" in muc_do:
      bg_color = "#854d0e"
      icon = "⚠️"

    cards.append({
        "label": item.get("label", "WORKDAY"),
        "date_str": d_obj.strftime("%d/%m"),
        "wfh_status": item.get("khuyen_nghi_wfh", "ĐẾN VĂN PHÒNG"),
        "wfh_reason": item.get("ly_do_wfh", "Thời tiết ổn định"),
        "bg_color": bg_color,
        "icon": icon,
        "dinh_trieu": item.get("dinh_trieu", "--"),
        "gio_trieu": item.get("gio_dinh_trieu", "--"),
        "bao_dong": item.get("bao_dong", "--"),
        "morning_rain": w_data["morning_rain"],
        "morning_prob": w_data["morning_prob"],
        "evening_rain": w_data["evening_rain"],
        "evening_prob": w_data["evening_prob"],
    })

  return templates.TemplateResponse(
      "index.html",
      {
          "request": request,
          "now_time": now_vn.strftime("%H:%M:%S"),
          "now_date": now_vn.strftime("%d/%m/%Y"),
          "cards": cards,
      },
  )
