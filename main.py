# main.py
# FastAPI + Open-Meteo（現在＋7日）/ ゆるキャラ3パターン表示

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==== 共通 ====
JP_DOW = ["月", "火", "水", "木", "金", "土", "日"]  # datetime.weekday(): 月=0

# --- アイコン（天気シンボル） ---
def icon_file_from_code(code: int) -> str:
    if code in (0,):                           # 快晴
        return "sun.svg"
    if code in (1, 2):                         # 晴れ/一部曇り
        return "sun.svg"
    if code in (3, 45, 48):                    # くもり/霧
        return "cloud.svg"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):  # 雨/にわか雨
        return "rain.svg"
    if code in (71, 73, 75, 77, 85, 86):       # 雪（なければ雲で代用）
        return "cloud.svg"
    if code in (95, 96, 99):                   # 雷（なければ雨で代用）
        return "rain.svg"
    return "cloud.svg"

def cute_icon(code: int) -> Dict[str, str]:
    file = icon_file_from_code(code)
    if file == "sun.svg":
        name = "たいよう"
    elif file == "rain.svg":
        name = "あめ"
    else:
        name = "くも"
    return {"file": file, "name": name}

# --- ゆるキャラ選択（3パターン） ---
def choose_character(weathercode: int, temp_c: float) -> str:
    """
    ルール：
      1) 雨系なら「傘キャラ」
      2) 気温が5℃以下なら「厚着キャラ」
      3) それ以外は「晴れ・あったかキャラ」
    * 優先順位は 雨 > 寒い > 晴れ
    """
    rain_codes = {51,53,55,56,57,61,63,65,66,67,80,81,82,95,96,99}
    if weathercode in rain_codes:
        return "character_rainy.png"
    if temp_c is not None and temp_c <= 5:
        return "character_cold.png"
    return "character_sunny.png"

# ==== API ====
async def geocode_city(city: str, lang: str = "ja") -> Optional[Dict[str, Any]]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": lang}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if not data.get("results"):
            return None
        res = data["results"][0]
        return {
            "name": res["name"],
            "lat": res["latitude"],
            "lon": res["longitude"],
            "country": res.get("country"),
        }

async def get_weather(lat: float, lon: float, tz: str = "auto") -> Dict[str, Any]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,  # temperature, windspeed, weathercode, is_day
        "daily": ["weathercode", "temperature_2m_max", "temperature_2m_min"],
        "forecast_days": 7,
        "timezone": tz,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

def build_daily_list(daily: Dict[str, Any]) -> List[Dict[str, Any]]:
    days = []
    times: List[str] = daily.get("time", [])
    tmaxs: List[float] = daily.get("temperature_2m_max", [])
    tmins: List[float] = daily.get("temperature_2m_min", [])
    wcodes: List[int] = daily.get("weathercode", [])
    for i, datestr in enumerate(times):
        try:
            dt = datetime.fromisoformat(datestr)
        except Exception:
            dt = datetime.utcnow()
        days.append({
            "date": datestr,
            "dow": JP_DOW[dt.weekday()],
            "tmax": round(tmaxs[i]) if i < len(tmaxs) else None,
            "tmin": round(tmins[i]) if i < len(tmins) else None,
            "file": icon_file_from_code(int(wcodes[i]) if i < len(wcodes) else 3),
        })
    return days

# ==== ルーティング ====
@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    city: str = Query("Zurich", description="都市名（例: Zurich, Genève, Bern, Lausanne, Lugano）"),
):
    try:
        loc = await geocode_city(city)
        if not loc:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": f"場所『{city}』が見つかりませんでした。"}
            )

        w = await get_weather(loc["lat"], loc["lon"])
        cw = w.get("current_weather", {})
        daily_list = build_daily_list(w.get("daily", {}))

        # 天気シンボル
        icon = cute_icon(int(cw.get("weathercode", 3)))
        # ゆるキャラ（3パターン）
        character_file = choose_character(
            weathercode=int(cw.get("weathercode", 3)),
            temp_c=float(cw.get("temperature", 0))
        )

        ctx = {
            "request": request,
            "city": loc["name"],
            "country": loc["country"],
            "temp": round(cw.get("temperature", 0)),
            "windspeed": cw.get("windspeed", 0),
            "time": cw.get("time", ""),
            "icon": icon,                # 大きい天気シンボル
            "character": character_file, # 横に出すゆるキャラ
            "daily": daily_list,         # 7日カード
            "query_city": city,
        }
        return templates.TemplateResponse("index.html", ctx)

    except httpx.HTTPError as e:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"API通信でエラー: {e}"}
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"想定外のエラー: {e}"}
        )

# 開発用
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
