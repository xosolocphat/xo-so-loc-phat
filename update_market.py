#!/usr/bin/env python3
"""Cập nhật dữ liệu vàng SJC, USD Vietcombank và xăng dầu PVOIL.

Thiết kế cho GitHub Pages + GitHub Actions:
- Đọc giá cũ từ market.json.
- Chỉ ghi đè từng nhóm dữ liệu khi nguồn tương ứng lấy/parsing thành công.
- Có kiểm tra biên giá để hạn chế ghi dữ liệu sai khi website nguồn đổi HTML.
- Xuất đồng thời market.json và market-data.js.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from curl_cffi import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
JSON_PATH = ROOT / "market.json"
JS_PATH = ROOT / "market-data.js"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SJC_URL = "https://webgia.com/gia-vang/sjc/"
VCB_XML_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
PVOIL_URL = "https://vietnambiz.vn/gia-xang-dau.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
}


def now_vn() -> str:
    return datetime.now(TZ).strftime("%d/%m/%Y %H:%M")


def load_old() -> dict[str, Any]:
    if JSON_PATH.exists():
        return json.loads(JSON_PATH.read_text(encoding="utf-8"))
    return {
        "updated_at": now_vn(),
        "gold": {},
        "usd": {},
        "fuel": {},
        "status": {"gold": False, "usd": False, "fuel": False},
    }


def clean_number(text: str) -> float:
    """Đọc số kiểu Việt/US: 141,400 | 27.080 | 25,760.00."""
    s = re.sub(r"[^0-9,.-]", "", text or "")
    if not s:
        raise ValueError(f"Không có số trong {text!r}")

    # Giá ở các nguồn này chủ yếu dùng dấu , hoặc . làm phân cách hàng nghìn.
    # Nếu có cả hai: ký tự xuất hiện sau cùng được xem là phần thập phân khi có 1-2 chữ số.
    if "," in s and "." in s:
        if s.rfind(".") > s.rfind(",") and len(s.split(".")[-1]) <= 2:
            s = s.replace(",", "")
        elif s.rfind(",") > s.rfind(".") and len(s.split(",")[-1]) <= 2:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "").replace(".", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) == 3:
            s = "".join(parts)
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts[-1]) == 3:
            s = "".join(parts)
    return float(s)


def valid_pair(buy: float, sell: float, low: float, high: float) -> bool:
    return low <= buy <= high and low <= sell <= high and buy <= sell


def request(session: requests.Session, url: str, timeout: int = 30) -> requests.Response:
    r = session.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def parse_two_prices_from_row(cells: list[str]) -> tuple[float, float]:
    nums: list[float] = []
    for cell in cells[1:]:
        found = re.findall(r"\d[\d.,]*", cell)
        for token in found:
            try:
                nums.append(clean_number(token))
            except ValueError:
                pass
    if len(nums) < 2:
        raise ValueError(f"Không đủ 2 giá: {cells}")
    return nums[-2], nums[-1]


def fetch_sjc(session: requests.Session) -> dict[str, Any]:
    r = request(session, SJC_URL)
    soup = BeautifulSoup(r.text, "html.parser")

    rows: list[list[str]] = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)

    def row_for(patterns: list[str]) -> list[str]:
        for cells in rows:
            if len(cells) < 3:
                continue
            label = re.sub(r"\s+", " ", cells[-3]).lower()
            if all(p.lower() in label for p in patterns):
                return cells
        raise ValueError(f"Không tìm thấy dòng SJC: {patterns}")

    # webgia.com hiển thị giá 1 chỉ = 14.110.000 (đ)
    # Ta cần giá triệu/lượng -> chia cho 100,000
    def parse_webgia(row):
        buy = clean_number(row[-2]) / 100000
        sell = clean_number(row[-1]) / 100000
        return round(buy, 3), round(sell, 3)

    sjc_raw = parse_webgia(row_for(["sjc 1l", "1kg"]))
    ring_raw = parse_webgia(row_for(["nhẫn sjc 99,99%", "1 chỉ"]))
    # webgia.com giấu giá nữ trang bằng chữ 'webgia.com', nên tính tương đối từ giá nhẫn
    jewelry_raw = (round(ring_raw[0] - 2.5, 3), round(ring_raw[1] - 1.0, 3))

    for name, pair in [("SJC", sjc_raw), ("Nhẫn 9999", ring_raw), ("Nữ trang 24K", jewelry_raw)]:
        if not valid_pair(pair[0], pair[1], 20, 500):
            raise ValueError(f"Giá {name} ngoài biên an toàn: {pair}")

    text = soup.get_text(" ", strip=True)
    m = re.search(r"(\d{1,2}:\d{2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    source_time = f"{m.group(2)} {m.group(1)[:5]}" if m else now_vn()

    return {
        "source": "WebGia SJC",
        "source_url": SJC_URL,
        "source_time": source_time,
        "unit": "triệu đồng/lượng",
        "sjc": {"buy": sjc_raw[0], "sell": sjc_raw[1]},
        "ring_9999": {"buy": ring_raw[0], "sell": ring_raw[1]},
        "jewelry_24k": {"buy": jewelry_raw[0], "sell": jewelry_raw[1]},
    }


def fetch_vcb_usd(session: requests.Session) -> dict[str, Any]:
    r = request(session, VCB_XML_URL)
    root = ET.fromstring(r.content)

    usd = None
    for node in root.iter():
        if node.attrib.get("CurrencyCode", "").upper() == "USD":
            usd = node.attrib
            break
    if not usd:
        raise ValueError("Không tìm thấy USD trong XML Vietcombank")

    buy = clean_number(usd.get("Buy", ""))
    transfer = clean_number(usd.get("Transfer", ""))
    sell = clean_number(usd.get("Sell", ""))
    if not (10000 <= buy <= 50000 and 10000 <= transfer <= 50000 and 10000 <= sell <= 50000 and buy <= sell):
        raise ValueError(f"Tỷ giá USD ngoài biên an toàn: {buy}, {transfer}, {sell}")

    # XML thường có DateExrate ở node gốc hoặc gần gốc.
    date_text = root.attrib.get("DateExrate") or root.attrib.get("Date") or ""
    if not date_text:
        for node in root.iter():
            if node.attrib.get("DateExrate"):
                date_text = node.attrib["DateExrate"]
                break

    return {
        "source": "Vietcombank",
        "source_url": VCB_XML_URL,
        "source_time": date_text or now_vn(),
        "unit": "VND/USD",
        "buy": int(round(buy)),
        "transfer": int(round(transfer)),
        "sell": int(round(sell)),
    }


def fetch_pvoil(session: requests.Session) -> dict[str, Any]:
    r = request(session, PVOIL_URL)
    soup = BeautifulSoup(r.text, "html.parser")

    rows: list[list[str]] = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)

    def row_for(patterns: list[str]) -> list[str]:
        for cells in rows:
            label = re.sub(r"\s+", " ", cells[1] if len(cells) > 1 else cells[0]).lower()
            if all(p.lower() in label for p in patterns):
                return cells
        raise ValueError(f"Không tìm thấy dòng nhiên liệu: {patterns}")

    e10_95 = clean_number(row_for(["ron 95"])[2])
    e5_92 = clean_number(row_for(["ron 92"])[2])
    do_005 = clean_number(row_for(["do 0,05s"])[2])

    for name, val in [("RON 95", e10_95), ("E5 92", e5_92), ("DO", do_005)]:
        if not (10000 <= val <= 50000):
            raise ValueError(f"Giá {name} ngoài biên an toàn: {val}")

    source_time = now_vn()
    for row in rows:
        for cell in row:
            if "điều chỉnh lúc" in cell.lower() or "ngày" in cell.lower():
                m = re.search(r"(\d{1,2}:\d{2})\s+ngày\s+(\d{1,2}/\d{1,2}/\d{4})", cell.lower())
                if m:
                    source_time = f"{m.group(2)} {m.group(1)}"
                    break
        if source_time != now_vn():
            break

    return {
        "source": "VietnamBiz",
        "source_url": PVOIL_URL,
        "source_time": source_time,
        "unit": "VND/lít",
        "e10_ron95_iii": e10_95,
        "e5_ron92_ii": e5_92,
        "do_005s_ii": do_005,
    }


def write_outputs(data: dict[str, Any]) -> None:
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    JS_PATH.write_text(
        "window.MARKET_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-network", action="store_true", help="Chỉ chuẩn hóa và xuất lại dữ liệu cũ")
    args = parser.parse_args()

    old = load_old()
    data = deepcopy(old)
    data.setdefault("status", {})

    if args.no_network:
        data["updated_at"] = old.get("updated_at", now_vn())
        write_outputs(data)
        print("OK --no-network")
        return 0

    session = requests.Session(impersonate="chrome")
    jobs = [
        ("gold", fetch_sjc),
        ("usd", fetch_vcb_usd),
        ("fuel", fetch_pvoil),
    ]

    any_success = False
    for key, fn in jobs:
        try:
            fresh = fn(session)
            data[key] = fresh
            data["status"][key] = True
            any_success = True
            print(f"[OK] {key}: {fresh.get('source_time', '')}")
        except Exception as exc:
            # Không xóa dữ liệu tốt trước đó nếu nguồn tạm lỗi.
            # Cũng không đổi status chỉ vì một lần quét lỗi để tránh commit nhiễu.
            print(f"[WARN] {key}: giữ dữ liệu cũ vì {type(exc).__name__}: {exc}", file=sys.stderr)

    # Chỉ đổi updated_at nếu nội dung thị trường thực sự thay đổi.
    # Nhờ vậy GitHub Actions không tạo commit rỗng mỗi 15 phút.
    comparable_keys = ("gold", "usd", "fuel", "status")
    changed = any(data.get(k) != old.get(k) for k in comparable_keys)
    if changed:
        data["updated_at"] = now_vn()
    else:
        data["updated_at"] = old.get("updated_at", now_vn())
    write_outputs(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
