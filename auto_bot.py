#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTO BOT V2 - XỔ SỐ PHÁT ĐẠT

Mục tiêu:
- Cập nhật kết quả xổ số truyền thống vào index.html.
- Cập nhật Vietlott Mega 6/45 + Power 6/55 vào vietlott.json.
- Giữ lịch sử Vietlott còn hạn lĩnh thưởng 60 ngày.
- KHÔNG sinh dữ liệu xổ số giả khi nguồn lỗi.
- Không nhúng API key trực tiếp trong mã nguồn.

Chế độ:
  python auto_bot_v2.py --mode quick     # nhanh: hôm nay + Vietlott
  python auto_bot_v2.py --mode full      # đầy đủ: 95 ngày + thống kê + Vietlott
  python auto_bot_v2.py --mode vietlott  # chỉ cập nhật Vietlott

Biến môi trường tùy chọn:
  PHA_API_KEY=xs_...  # ưu tiên API PHA cho Vietlott nếu có

Nguồn Vietlott:
1) PHA API (nếu có PHA_API_KEY)
2) Dataset công khai vietvudanh/vietlott-data (MIT) cho bộ số/lịch sử
3) Trang kết quả công khai xoso.com.vn để bổ sung Jackpot/số lượng giải (fallback)

Lưu ý: GitHub Actions có thể bị các website chặn IP trung tâm dữ liệu. Bot luôn giữ dữ liệu
đã có nếu nguồn mới lỗi, thay vì ghi dữ liệu giả.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
VIETLOTT_FILE = ROOT / "vietlott.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.6"}
TIMEOUT = 15

# -------------------------
# CẤU HÌNH ĐÀI TRUYỀN THỐNG
# -------------------------
MAP_DAI = {
    "mb": "Miền Bắc",
    "bdi": "Bình Định", "dnang": "Đà Nẵng", "dlk": "Đắk Lắk", "kh": "Khánh Hòa",
    "kt": "Kon Tum", "nt": "Ninh Thuận", "py": "Phú Yên", "qnam": "Quảng Nam",
    "qngai": "Quảng Ngãi", "qt": "Quảng Trị", "tthue": "Thừa Thiên Huế",
    "qb": "Quảng Bình", "gl": "Gia Lai", "dno": "Đắk Nông",
    "ag": "An Giang", "bl": "Bạc Liêu", "bt": "Bến Tre", "bd": "Bình Dương",
    "bp": "Bình Phước", "bth": "Bình Thuận", "cmau": "Cà Mau", "ctho": "Cần Thơ",
    "dl": "Đà Lạt", "dn": "Đồng Nai", "dthap": "Đồng Tháp", "hg": "Hậu Giang",
    "kg": "Kiên Giang", "la": "Long An", "st": "Sóc Trăng", "tn": "Tây Ninh",
    "tg": "Tiền Giang", "tv": "Trà Vinh", "vl": "Vĩnh Long", "vt": "Vũng Tàu",
    "hcm": "TP. HCM",
}

ALIASES = {
    "tp. hcm": "hcm", "hồ chí minh": "hcm", "tphcm": "hcm", "tp hcm": "hcm",
    "đà lạt": "dl", "da lat": "dl",
    "bà rịa vũng tàu": "vt", "vũng tàu": "vt",
    "thừa t. huế": "tthue", "thừa thiên huế": "tthue", "tt huế": "tthue", "huế": "tthue",
    "miền bắc": "mb", "truyền thống": "mb",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def normalize_name(name: str) -> Optional[str]:
    n = re.sub(r"\s+", " ", (name or "").lower().strip())
    for alias, code in ALIASES.items():
        if alias in n:
            return code
    for code, real_name in MAP_DAI.items():
        if real_name.lower() in n:
            return code
    return None


def normalize_prize_name(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    tl = t.lower()
    if "đặc biệt" in tl:
        return "ĐB"
    m = re.search(r"(?:giải|g)\s*([1-8])", tl)
    if m:
        return f"G{m.group(1)}"
    # Một số bảng dùng chỉ số 1..8 trực tiếp
    if t in {str(i) for i in range(1, 9)}:
        return f"G{t}"
    return t


def extract_2_digits(text: str) -> List[str]:
    tokens = re.findall(r"\b\d+\b", text or "")
    return [t[-2:] for t in tokens if len(t) >= 2]


# -------------------------
# XỔ SỐ TRUYỀN THỐNG
# -------------------------
def _parse_xskt_table(table: Any, mien: str, want_2digit: bool = False) -> Dict[str, Dict[str, Any]]:
    """Parse một bảng XSKT, trả về {code: {G8:..., ...}}."""
    out: Dict[str, Dict[str, Any]] = defaultdict(dict)
    trs = table.find_all("tr")
    if not trs:
        return {}

    if mien == "xsmb":
        dais = ["mb"]
    else:
        dais = []
        header_cells = trs[0].find_all(["th", "td"])[1:]
        for th in header_cells:
            dais.append(normalize_name(th.get_text(" ", strip=True)) or "")

    for tr in trs[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        ten_giai = normalize_prize_name(tds[0].get_text(" ", strip=True))
        if not ten_giai:
            continue
        for idx, td_cell in enumerate(tds[1:]):
            if idx >= len(dais) or not dais[idx]:
                continue
            raw = td_cell.get_text(" - ", strip=True)
            if want_2digit:
                nums = extract_2_digits(raw)
                out[dais[idx]].setdefault("_2digits", []).extend(nums)
            out[dais[idx]][ten_giai] = raw
    return dict(out)


def crawl_xskt_today_full_results(session: Optional[requests.Session] = None) -> Dict[str, Dict[str, Any]]:
    """Lấy kết quả hôm nay của 3 miền từ xskt.com.vn."""
    session = session or new_session()
    db: Dict[str, Dict[str, Any]] = defaultdict(dict)
    today = dt.date.today()
    today_short = today.strftime("%d/%m")

    log("🔄 Đang lấy kết quả xổ số hôm nay...")
    for mien in ("xsmb", "xsmt", "xsmn"):
        url = f"https://xskt.com.vn/{mien}"
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            found = False
            for table in soup.find_all("table"):
                tid = str(table.get("id", ""))
                if not any(x in tid for x in ("MB0", "MT0", "MN0")):
                    continue
                text = table.get_text(" ", strip=True)
                if today_short not in text:
                    continue
                parsed = _parse_xskt_table(table, mien, want_2digit=False)
                for code, result in parsed.items():
                    db[code].update(result)
                found = True
            if not found:
                log(f"⚠️ Chưa thấy bảng hôm nay ở {url}")
        except Exception as e:
            log(f"⚠️ Lỗi lấy {url}: {e}")

    date_vn = today.strftime("%d/%m/%Y")
    for result in db.values():
        result["ngay"] = date_vn
    return dict(db)


def crawl_xskt_history(days: int = 95, session: Optional[requests.Session] = None) -> Tuple[Dict[str, List[List[str]]], Dict[str, List[Dict[str, Any]]]]:
    """
    Lấy lịch sử thật. Nếu nguồn thiếu dữ liệu thì để thiếu, KHÔNG sinh số giả.
    Trả về:
      - final_db[code] = list các kỳ, mỗi kỳ là list 2 số cuối
      - db_ket_qua[code] = danh sách kết quả đầy đủ (30 ngày gần nhất)
    """
    session = session or new_session()
    db_2d: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    db_ket_qua: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    today = dt.date.today()

    log(f"🔄 Đang lấy lịch sử {days} ngày (không dùng dữ liệu giả)...")
    for i in range(days):
        d = today - dt.timedelta(days=i)
        date_slug = f"{d.day}-{d.month}-{d.year}"
        date_vn = d.strftime("%d/%m/%Y")

        for mien in ("xsmb", "xsmt", "xsmn"):
            url = f"https://xskt.com.vn/{mien}/ngay-{date_slug}"
            try:
                r = session.get(url, timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for table in soup.find_all("table"):
                    tid = str(table.get("id", ""))
                    if not any(x in tid for x in ("MB0", "MT0", "MN0")):
                        continue
                    parsed = _parse_xskt_table(table, mien, want_2digit=True)
                    for code, result in parsed.items():
                        nums = result.pop("_2digits", [])
                        if nums:
                            db_2d[code][date_slug].extend(nums)
                        if i < 30 and result:
                            entry = {"ngay": date_vn, **result}
                            # tránh trùng cùng ngày nếu page có nhiều bảng lặp
                            existing = next((x for x in db_ket_qua[code] if x.get("ngay") == date_vn), None)
                            if existing:
                                existing.update(entry)
                            else:
                                db_ket_qua[code].append(entry)
            except Exception as e:
                log(f"⚠️ {url}: {e}")

        if (i + 1) % 10 == 0:
            log(f"   Đã xử lý {i + 1}/{days} ngày")
        time.sleep(0.10)

    final_db: Dict[str, List[List[str]]] = {}
    for code in MAP_DAI:
        daily_lists: List[List[str]] = []
        for i in range(days):
            d = today - dt.timedelta(days=i)
            slug = f"{d.day}-{d.month}-{d.year}"
            nums = db_2d[code].get(slug, [])
            # Chỉ nhận kỳ có lượng số hợp lý; không fallback ngẫu nhiên.
            if len(nums) >= 16:
                daily_lists.append(nums)
        final_db[code] = daily_lists
        db_ket_qua[code].sort(key=lambda x: dt.datetime.strptime(x["ngay"], "%d/%m/%Y"), reverse=True)

    return final_db, dict(db_ket_qua)


def tinh_toan_xac_suat_thong_ke(lich_su_giai: List[List[str]], so_ky: int) -> Dict[str, List[Dict[str, Any]]]:
    du_lieu = lich_su_giai[:so_ky]
    if not du_lieu:
        return {"ve_nhieu": [], "chua_ve": []}

    tat_ca = [so for ky in du_lieu for so in ky]
    dem_so = {f"{i:02d}": 0 for i in range(100)}
    for so in tat_ca:
        if so in dem_so:
            dem_so[so] += 1

    danh_sach_ve = sorted(dem_so.items(), key=lambda x: (-x[1], x[0]))
    top_7_ve = [{"s": so, "l": lan} for so, lan in danh_sach_ve[:7]]

    dem_gan: Dict[str, int] = {}
    for i in range(100):
        so_tim = f"{i:02d}"
        ngay_vang = 0
        for ky in du_lieu:
            if so_tim in ky:
                break
            ngay_vang += 1
        dem_gan[so_tim] = ngay_vang

    danh_sach_gan = sorted(dem_gan.items(), key=lambda x: (-x[1], x[0]))
    top_7_gan = [{"s": so, "l": ngay} for so, ngay in danh_sach_gan[:7]]
    return {"ve_nhieu": top_7_ve, "chua_ve": top_7_gan}


# -------------------------
# ĐỌC/GHI KHỐI DATA TRONG INDEX.HTML
# -------------------------
def read_index_databases() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not INDEX_FILE.exists():
        return {}, {}
    content = INDEX_FILE.read_text(encoding="utf-8")
    if "// ---PYTHON_DATA_START---" not in content or "// ---PYTHON_DATA_END---" not in content:
        return {}, {}
    block = content.split("// ---PYTHON_DATA_START---", 1)[1].split("// ---PYTHON_DATA_END---", 1)[0]
    m1 = re.search(r"const\s+dbXacSuat\s*=\s*(\{.*?\})\s*;\s*const\s+dbKetQua", block, re.S)
    m2 = re.search(r"const\s+dbKetQua\s*=\s*(\{.*\})\s*;", block, re.S)
    try:
        db_xs = json.loads(m1.group(1)) if m1 else {}
    except Exception:
        db_xs = {}
    try:
        db_kq = json.loads(m2.group(1)) if m2 else {}
    except Exception:
        db_kq = {}
    return db_xs, db_kq


def write_index_databases(db_xs: Dict[str, Any], db_kq: Dict[str, Any]) -> bool:
    if not INDEX_FILE.exists():
        log(f"❌ Không tìm thấy {INDEX_FILE.name}")
        return False

    content = INDEX_FILE.read_text(encoding="utf-8")
    start_tag = "// ---PYTHON_DATA_START---"
    end_tag = "// ---PYTHON_DATA_END---"
    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag)
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        log("❌ Không tìm thấy cặp thẻ PYTHON_DATA trong index.html")
        return False

    payload = (
        "\nconst dbXacSuat = " + json.dumps(db_xs, ensure_ascii=False, separators=(",", ":")) + ";\n"
        "const dbKetQua = " + json.dumps(db_kq, ensure_ascii=False, separators=(",", ":")) + ";\n"
    )
    new_content = content[: start_idx + len(start_tag)] + payload + content[end_idx:]
    INDEX_FILE.write_text(new_content, encoding="utf-8")
    return True


def merge_today_into_history(db_kq: Dict[str, Any], today_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    today_vn = dt.date.today().strftime("%d/%m/%Y")
    out = dict(db_kq or {})
    for code, result in today_results.items():
        arr = list(out.get(code, []))
        found = False
        for item in arr:
            if item.get("ngay") == today_vn:
                item.update(result)
                found = True
                break
        if not found:
            arr.insert(0, result)
        # giữ 30 kỳ/ngày gần nhất đã có
        arr = arr[:30]
        out[code] = arr
    return out


# -------------------------
# VIETLOTT
# -------------------------
GITHUB_VIETLOTT = {
    "mega": "https://raw.githubusercontent.com/vietvudanh/vietlott-data/main/data/power645.jsonl",
    "power": "https://raw.githubusercontent.com/vietvudanh/vietlott-data/main/data/power655.jsonl",
}

XOSO_DETAIL_PAGES = {
    # Một trang/tựa game là đủ cho các kỳ gần đây; giảm tải khi chạy 15 phút/lần.
    "mega": ["https://xoso.com.vn/do-ket-qua-xo-so-mega.html"],
    "power": ["https://xoso.com.vn/xo-so-power-655.html"],
}



def _date_iso(value: Any) -> Optional[str]:
    s = str(value or "").strip().split("T")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _claimable(date_iso: str, days: int = 60) -> bool:
    try:
        d = dt.date.fromisoformat(date_iso)
    except Exception:
        return False
    return d + dt.timedelta(days=days) >= dt.date.today()


def _normalize_vietlott_draw(row: Dict[str, Any], kind: str, source: str) -> Optional[Dict[str, Any]]:
    date_iso = _date_iso(row.get("date") or row.get("draw_date"))
    draw_id = str(row.get("id") or row.get("drawId") or row.get("draw_id") or "").replace("#", "").strip()
    nums = row.get("numbers") or row.get("result") or row.get("balls")
    if not date_iso or not draw_id or not isinstance(nums, list) or len(nums) < 6:
        return None

    balls = []
    for x in nums[:6]:
        try:
            balls.append(int(x))
        except Exception:
            return None
    bonus = row.get("bonus")
    if bonus is None and kind == "power" and len(nums) >= 7:
        bonus = nums[6]
    try:
        bonus = int(bonus) if bonus is not None and str(bonus) != "" else None
    except Exception:
        bonus = None

    out: Dict[str, Any] = {
        "id": draw_id.zfill(5),
        "date": date_iso,
        "balls": balls,
        "bonus": bonus if kind == "power" else None,
        "source": source,
    }

    # Chỉ nhận các field nếu nguồn thực sự có; không suy diễn jackpot kỳ hiện tại từ "next jackpot".
    for key in ("jackpot", "jackpot1", "jackpot2"):
        if row.get(key) not in (None, ""):
            out[key] = row.get(key)
    counts = row.get("counts") or row.get("prizeCounts") or row.get("prize_counts")
    if isinstance(counts, dict):
        out["counts"] = counts
    return out


def fetch_jsonl_history(url: str, kind: str, session: requests.Session) -> List[Dict[str, Any]]:
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    rows: List[Dict[str, Any]] = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except Exception:
            continue
        d = _normalize_vietlott_draw(raw, kind, "github-vietlott-data")
        if d:
            rows.append(d)
    rows.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    return rows


def fetch_pha_history(kind: str, api_key: str, session: requests.Session, limit: int = 100) -> List[Dict[str, Any]]:
    game = "mega645" if kind == "mega" else "power655"
    url = "https://pha.vn/api/v1/dientoan"
    r = session.get(url, params={"game": game, "limit": limit}, headers={**HEADERS, "X-API-KEY": api_key}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"PHA trả trạng thái: {data.get('status')}")
    rows: List[Dict[str, Any]] = []
    for raw in data.get("draws", []):
        d = _normalize_vietlott_draw(raw, kind, "pha.vn")
        if d:
            # Nếu API trả jackpot kỳ tiếp theo, giữ riêng để không nhầm với Jackpot của kỳ đã quay.
            for k in ("next_jackpot", "jackpot_next", "nextJackpot"):
                if raw.get(k) not in (None, ""):
                    d["next_jackpot"] = raw.get(k)
                    break
            rows.append(d)
    rows.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    return rows


def _int_from_cell(text: str) -> Optional[int]:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else None


def crawl_xoso_prize_details(kind: str, session: requests.Session) -> Dict[str, Dict[str, Any]]:
    """Bổ sung Jackpot và số lượng giải từ các bảng công khai. Lỗi thì bỏ qua."""
    details: Dict[str, Dict[str, Any]] = {}
    for url in XOSO_DETAIL_PAGES[kind]:
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            nodes = soup.find_all(string=re.compile(r"Kỳ\s+quay\s+thưởng", re.I))
            for node in nodes:
                text = str(node)
                m = re.search(r"#\s*(\d{4,6})", text)
                if not m:
                    # đôi khi ID nằm ở parent text
                    parent_text = node.parent.get_text(" ", strip=True) if node.parent else text
                    m = re.search(r"#\s*(\d{4,6})", parent_text)
                if not m:
                    continue
                draw_id = m.group(1).zfill(5)
                table = node.parent.find_next("table") if node.parent else None
                if table is None:
                    continue

                item: Dict[str, Any] = {"source_detail": "xoso.com.vn"}
                counts: Dict[str, int] = {}
                good_rows = 0
                for tr in table.find_all("tr"):
                    cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                    if len(cells) < 3:
                        continue
                    label = cells[0].lower().strip()
                    count = _int_from_cell(cells[-2])
                    value = _int_from_cell(cells[-1])
                    if "jackpot 1" in label:
                        if value is not None:
                            item["jackpot"] = value
                        if count is not None:
                            counts["jackpot"] = count
                        good_rows += 1
                    elif "jackpot 2" in label:
                        if value is not None:
                            item["jackpot2"] = value
                        if count is not None:
                            counts["jackpot2"] = count
                        good_rows += 1
                    elif label == "jackpot" or label.startswith("jackpot "):
                        if value is not None:
                            item["jackpot"] = value
                        if count is not None:
                            counts["jackpot"] = count
                        good_rows += 1
                    elif "giải nhất" in label or label == "giải 1":
                        if count is not None:
                            counts["first"] = count
                        good_rows += 1
                    elif "giải nhì" in label or label == "giải 2":
                        if count is not None:
                            counts["second"] = count
                        good_rows += 1
                    elif "giải ba" in label or label == "giải 3":
                        if count is not None:
                            counts["third"] = count
                        good_rows += 1
                if good_rows >= 3:
                    item["counts"] = counts
                    # ưu tiên bản đầy đủ hơn nếu cùng ID xuất hiện nhiều trang
                    old = details.get(draw_id, {})
                    details[draw_id] = {**old, **item}
        except Exception as e:
            log(f"⚠️ Không lấy được chi tiết Vietlott từ {url}: {e}")
    return details


def merge_histories(*histories: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge theo ID; history đứng trước có độ ưu tiên cao hơn cho field đã có."""
    merged: Dict[str, Dict[str, Any]] = {}
    # đi ngược để danh sách đứng trước ghi đè sau cùng
    hs = list(histories)
    for hist in reversed(hs):
        for row in hist or []:
            key = str(row.get("id") or "").zfill(5)
            if not key.strip("0"):
                continue
            merged[key] = {**merged.get(key, {}), **row}
    out = list(merged.values())
    out.sort(key=lambda x: (x.get("date", ""), x.get("id", "")), reverse=True)
    return out


def load_previous_vietlott() -> Dict[str, Any]:
    if not VIETLOTT_FILE.exists():
        return {}
    try:
        return json.loads(VIETLOTT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def previous_history(data: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    arr = data.get(f"{kind}_history")
    if not isinstance(arr, list):
        arr = []
    latest = data.get(kind)
    if isinstance(latest, dict):
        arr = [latest, *arr]
    return [x for x in arr if isinstance(x, dict)]


def update_vietlott() -> bool:
    session = new_session()
    previous = load_previous_vietlott()
    pha_key = os.getenv("PHA_API_KEY", "").strip()
    output: Dict[str, Any] = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"),
        "claim_period_days": 60,
    }
    all_ok = False

    for kind in ("mega", "power"):
        gh: List[Dict[str, Any]] = []
        pha: List[Dict[str, Any]] = []
        try:
            gh = fetch_jsonl_history(GITHUB_VIETLOTT[kind], kind, session)
            log(f"✅ Vietlott {kind}: lấy {len(gh)} kỳ từ GitHub dataset")
        except Exception as e:
            log(f"⚠️ Vietlott {kind} GitHub lỗi: {e}")

        if pha_key:
            try:
                pha = fetch_pha_history(kind, pha_key, session, 100)
                log(f"✅ Vietlott {kind}: lấy {len(pha)} kỳ từ PHA")
            except Exception as e:
                log(f"⚠️ PHA {kind} lỗi, dùng nguồn dự phòng: {e}")

        prev = previous_history(previous, kind)
        history = merge_histories(pha, gh, prev)

        # Bổ sung Jackpot + số lượng giải. Nếu web phụ bị lỗi, dữ liệu cũ vẫn được giữ.
        try:
            details = crawl_xoso_prize_details(kind, session)
        except Exception:
            details = {}
        if details:
            for row in history:
                detail = details.get(str(row.get("id", "")).zfill(5))
                if detail:
                    row.update(detail)

        # Chỉ giữ các kỳ còn hạn lĩnh thưởng 60 ngày cho phần lịch sử hiển thị.
        claimable = [x for x in history if x.get("date") and _claimable(x["date"], 60)]
        claimable.sort(key=lambda x: (x.get("date", ""), x.get("id", "")), reverse=True)

        # Latest có thể là kỳ mới hơn 60 ngày hiển nhiên; nếu không có nguồn mới thì giữ bản cũ.
        latest = history[0] if history else (previous.get(kind) if isinstance(previous.get(kind), dict) else None)
        output[kind] = latest
        output[f"{kind}_history"] = claimable
        if latest:
            all_ok = True

    if not all_ok and previous:
        log("⚠️ Không lấy được Vietlott mới; giữ nguyên file vietlott.json cũ.")
        return False

    tmp = VIETLOTT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(VIETLOTT_FILE)
    log(f"✅ Đã ghi {VIETLOTT_FILE.name}")
    return True


# -------------------------
# ĐIỀU PHỐI
# -------------------------
def run_quick() -> None:
    """Cập nhật nhanh: kết quả hôm nay + Vietlott; giữ nguyên bảng thống kê lịch sử."""
    db_xs, db_kq = read_index_databases()
    if not db_xs and not db_kq:
        log("⚠️ Không đọc được dữ liệu cũ trong index.html; chuyển sang full.")
        run_full()
        return
    today = crawl_xskt_today_full_results()
    if today:
        db_kq = merge_today_into_history(db_kq, today)
        if write_index_databases(db_xs, db_kq):
            log("✅ Đã cập nhật nhanh kết quả hôm nay vào index.html")
    else:
        log("ℹ️ Chưa có kết quả hôm nay; giữ index.html hiện tại.")
    update_vietlott()


def run_full() -> None:
    session = new_session()
    history_2d, db_kq = crawl_xskt_history(95, session)
    today = crawl_xskt_today_full_results(session)
    if today:
        db_kq = merge_today_into_history(db_kq, today)

    moc_ky = [7, 15, 30, 60, 90]
    db_xs: Dict[str, Any] = {}
    for code in MAP_DAI:
        lich_su = history_2d.get(code, [])
        db_xs[code] = {}
        for ky in moc_ky:
            db_xs[code][str(ky)] = tinh_toan_xac_suat_thong_ke(lich_su, ky)

    if write_index_databases(db_xs, db_kq):
        log("✅ Đã cập nhật lịch sử + thống kê thật vào index.html")
    update_vietlott()


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto Bot V2 - Xổ Số Phát Đạt")
    parser.add_argument("--mode", choices=["quick", "full", "vietlott"], default="quick")
    args = parser.parse_args()

    log(f"🤖 AUTO BOT V2 - mode={args.mode}")
    if args.mode == "full":
        run_full()
    elif args.mode == "vietlott":
        update_vietlott()
    else:
        run_quick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
