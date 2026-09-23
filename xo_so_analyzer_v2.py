# -*- coding: utf-8 -*-
"""
XỔ SỐ MIỀN NAM ANALYZER V2
Nguồn: XSKT.com.vn (chính) + MinhNgoc.net.vn (dự phòng/đối chiếu)
Tính năng:
- Tự tải kết quả XSMN theo khoảng ngày.
- Lưu SQLite, không tải lại dữ liệu đã có.
- Lọc theo tỉnh.
- Thống kê 00-99: số lần xuất hiện, số ngày có xuất hiện, tỷ lệ lịch sử,
  lần gần nhất, số kỳ chưa xuất hiện, tần suất 7/30/90/180/365 ngày.
- Biểu đồ Top 20.
- Xem lịch sử kết quả.
- Backtest đơn giản chiến lược "chọn Top K số nóng theo N ngày trước".
- Xuất CSV.

LƯU Ý:
Đây là công cụ thống kê dữ liệu lịch sử. Nó KHÔNG chứng minh một số có xác suất
cao hơn trong kỳ quay tiếp theo. Nếu quá trình quay là ngẫu nhiên/công bằng,
tần suất quá khứ không làm thay đổi xác suất thật của lần quay kế tiếp.

Cài:
    pip install requests beautifulsoup4 pandas matplotlib openpyxl

Chạy:
    python xo_so_analyzer_v2.py
"""

import os
import re
import math
import time
import sqlite3
import threading
import traceback
import unicodedata
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import Counter, defaultdict

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import requests
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib.pyplot as plt


APP_NAME = "Xổ Số Miền Nam Analyzer V2"
DB_FILE = Path(__file__).with_name("xoso_mien_nam.sqlite3")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

REQUEST_TIMEOUT = 20
POLITE_DELAY = 0.45

PRIZE_ORDER = ["G8", "G7", "G6", "G5", "G4", "G3", "G2", "G1", "DB"]
PRIZE_LENGTH = {"G8": 2, "G7": 3, "G6": 4, "G5": 4,
                "G4": 5, "G3": 5, "G2": 5, "G1": 5, "DB": 6}
PRIZE_COUNT = {"G8": 1, "G7": 1, "G6": 3, "G5": 1,
               "G4": 7, "G3": 2, "G2": 1, "G1": 1, "DB": 1}

# Lịch XSMN phổ biến theo tên đang hiển thị trên các trang nguồn.
SOUTH_SCHEDULE = {
    0: ["Hồ Chí Minh", "Đồng Tháp", "Cà Mau"],                     # Thứ 2
    1: ["Bến Tre", "Vũng Tàu", "Bạc Liêu"],                       # Thứ 3
    2: ["Đồng Nai", "Cần Thơ", "Sóc Trăng"],                       # Thứ 4
    3: ["Tây Ninh", "An Giang", "Bình Thuận"],                     # Thứ 5
    4: ["Vĩnh Long", "Bình Dương", "Trà Vinh"],                    # Thứ 6
    5: ["Hồ Chí Minh", "Long An", "Bình Phước", "Hậu Giang"],      # Thứ 7
    6: ["Tiền Giang", "Kiên Giang", "Đà Lạt"],                     # CN
}

ALL_PROVINCES = sorted({p for v in SOUTH_SCHEDULE.values() for p in v})

PROVINCE_ALIASES = {
    "tp hcm": "Hồ Chí Minh",
    "tp. hcm": "Hồ Chí Minh",
    "tphcm": "Hồ Chí Minh",
    "ho chi minh": "Hồ Chí Minh",
    "hồ chí minh": "Hồ Chí Minh",
    "sai gon": "Hồ Chí Minh",
    "sài gòn": "Hồ Chí Minh",
    "da lat": "Đà Lạt",
    "đà lạt": "Đà Lạt",
    "ba ria vung tau": "Vũng Tàu",
    "bà rịa vũng tàu": "Vũng Tàu",
}

MINHNGOC_NAMES = {
    "Hồ Chí Minh": ["TP. HCM", "Hồ Chí Minh", "TP HCM"],
    "Đồng Tháp": ["Đồng Tháp"],
    "Cà Mau": ["Cà Mau"],
    "Bến Tre": ["Bến Tre"],
    "Vũng Tàu": ["Vũng Tàu"],
    "Bạc Liêu": ["Bạc Liêu"],
    "Đồng Nai": ["Đồng Nai"],
    "Cần Thơ": ["Cần Thơ"],
    "Sóc Trăng": ["Sóc Trăng"],
    "Tây Ninh": ["Tây Ninh"],
    "An Giang": ["An Giang"],
    "Bình Thuận": ["Bình Thuận"],
    "Vĩnh Long": ["Vĩnh Long"],
    "Bình Dương": ["Bình Dương"],
    "Trà Vinh": ["Trà Vinh"],
    "Long An": ["Long An"],
    "Bình Phước": ["Bình Phước"],
    "Hậu Giang": ["Hậu Giang"],
    "Tiền Giang": ["Tiền Giang"],
    "Kiên Giang": ["Kiên Giang"],
    "Đà Lạt": ["Đà Lạt", "Da Lat"],
}


def strip_accents(s):
    s = str(s or "")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def norm_text(s):
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_province(name):
    raw = str(name or "").strip()
    n = norm_text(raw)
    for key, val in PROVINCE_ALIASES.items():
        if norm_text(key) == n:
            return val
    for p in ALL_PROVINCES:
        pn = norm_text(p)
        if n == pn or pn in n or n in pn:
            return p
    return raw


def canonical_prize(label):
    n = norm_text(label).replace(" ", "")
    mapping = {
        "g8": "G8", "giai8": "G8", "giaitam": "G8",
        "g7": "G7", "giai7": "G7", "giaibay": "G7",
        "g6": "G6", "giai6": "G6", "giaisau": "G6",
        "g5": "G5", "giai5": "G5", "giainam": "G5",
        "g4": "G4", "giai4": "G4", "giaitu": "G4",
        "g3": "G3", "giai3": "G3", "giaiba": "G3",
        "g2": "G2", "giai2": "G2", "giainhi": "G2",
        "g1": "G1", "giai1": "G1", "giainhat": "G1",
        "db": "DB", "gdb": "DB", "giaidb": "DB",
        "giaidacbiet": "DB", "dacbiet": "DB",
    }
    return mapping.get(n)


def pure_digit_tokens(text):
    return re.findall(r"(?<![A-Za-zÀ-ỹ0-9])(\d+)(?![A-Za-zÀ-ỹ0-9])", str(text))


def numbers_for_prize(text, prize):
    length = PRIZE_LENGTH[prize]
    need = PRIZE_COUNT[prize]
    nums = [x for x in pure_digit_tokens(text) if len(x) == length]
    return nums[:need]


def expected_total_results(province_count=1):
    return 18 * province_count


class LotteryDB:
    def __init__(self, path=DB_FILE):
        self.path = str(path)
        self.init_db()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def init_db(self):
        with self.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS results(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draw_date TEXT NOT NULL,
                    province TEXT NOT NULL,
                    prize TEXT NOT NULL,
                    number TEXT NOT NULL,
                    occurrence_index INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(draw_date, province, prize, occurrence_index)
                )
            """)

            cols = [r[1] for r in con.execute("PRAGMA table_info(results)").fetchall()]
            if "occurrence_index" not in cols:
                # CSDL bản cũ: tạo bảng mới để hỗ trợ trùng số cùng giải.
                con.execute("ALTER TABLE results RENAME TO results_old")
                con.execute("""
                    CREATE TABLE results(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        draw_date TEXT NOT NULL,
                        province TEXT NOT NULL,
                        prize TEXT NOT NULL,
                        number TEXT NOT NULL,
                        occurrence_index INTEGER NOT NULL DEFAULT 0,
                        source TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        UNIQUE(draw_date, province, prize, occurrence_index)
                    )
                """)
                old_rows = con.execute(
                    "SELECT draw_date,province,prize,number,source,fetched_at FROM results_old ORDER BY id"
                ).fetchall()
                counters = {}
                for rr in old_rows:
                    key = (rr[0], rr[1], rr[2])
                    counters[key] = counters.get(key, 0) + 1
                    con.execute(
                        "INSERT OR IGNORE INTO results(draw_date,province,prize,number,occurrence_index,source,fetched_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (rr[0], rr[1], rr[2], rr[3], counters[key], rr[4], rr[5])
                    )
                con.execute("DROP TABLE results_old")

            con.execute("""
                CREATE TABLE IF NOT EXISTS fetch_log(
                    draw_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    source TEXT,
                    row_count INTEGER DEFAULT 0,
                    message TEXT,
                    fetched_at TEXT NOT NULL
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_results_date ON results(draw_date)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_results_province ON results(province)")
            con.commit()

    def upsert_results(self, draw_date, rows, source):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            # Khi đã tải thành công 1 ngày, thay dữ liệu ngày đó để tránh trùng nguồn.
            con.execute("DELETE FROM results WHERE draw_date=?", (draw_date.isoformat(),))
            occurrence_counter = defaultdict(int)
            for r in rows:
                key = (r["province"], r["prize"])
                occurrence_counter[key] += 1
                occ = occurrence_counter[key]
                con.execute("""
                    INSERT OR REPLACE INTO results
                    (draw_date, province, prize, number, occurrence_index, source, fetched_at)
                    VALUES(?,?,?,?,?,?,?)
                """, (draw_date.isoformat(), r["province"], r["prize"],
                      r["number"], occ, source, now))
            con.execute("""
                INSERT INTO fetch_log(draw_date,status,source,row_count,message,fetched_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(draw_date) DO UPDATE SET
                  status=excluded.status,
                  source=excluded.source,
                  row_count=excluded.row_count,
                  message=excluded.message,
                  fetched_at=excluded.fetched_at
            """, (draw_date.isoformat(), "ok", source, len(rows), "", now))
            con.commit()

    def log_failure(self, draw_date, source, message):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("""
                INSERT INTO fetch_log(draw_date,status,source,row_count,message,fetched_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(draw_date) DO UPDATE SET
                  status=excluded.status,
                  source=excluded.source,
                  row_count=excluded.row_count,
                  message=excluded.message,
                  fetched_at=excluded.fetched_at
            """, (draw_date.isoformat(), "error", source, 0, message[:500], now))
            con.commit()

    def has_day(self, draw_date):
        with self.connect() as con:
            row = con.execute(
                "SELECT COUNT(*) c FROM results WHERE draw_date=?",
                (draw_date.isoformat(),)
            ).fetchone()
            return int(row["c"]) > 0

    def dataframe(self, start_date=None, end_date=None, province=None):
        sql = "SELECT draw_date,province,prize,number,source FROM results WHERE 1=1"
        args = []
        if start_date:
            sql += " AND draw_date>=?"
            args.append(start_date.isoformat())
        if end_date:
            sql += " AND draw_date<=?"
            args.append(end_date.isoformat())
        if province and province != "Tất cả":
            sql += " AND province=?"
            args.append(province)
        sql += " ORDER BY draw_date, province, id"
        with self.connect() as con:
            df = pd.read_sql_query(sql, con, params=args)
        if not df.empty:
            df["draw_date"] = pd.to_datetime(df["draw_date"])
        return df

    def available_provinces(self):
        with self.connect() as con:
            rows = con.execute("SELECT DISTINCT province FROM results ORDER BY province").fetchall()
        return [r["province"] for r in rows]

    def database_range(self):
        with self.connect() as con:
            row = con.execute("SELECT MIN(draw_date) mn, MAX(draw_date) mx, COUNT(*) c FROM results").fetchone()
        return row["mn"], row["mx"], int(row["c"] or 0)


class WebFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def get_html(self, url):
        last_err = None
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if r.status_code == 404:
                    raise RuntimeError("Trang không tồn tại (404)")
                r.raise_for_status()
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            except Exception as e:
                last_err = e
                time.sleep(1.0 + attempt)
        raise RuntimeError(str(last_err))

    def fetch_xskt(self, d):
        url = f"https://xskt.com.vn/xsmn/ngay-{d.day}-{d.month}-{d.year}"
        html = self.get_html(url)
        rows = self.parse_xskt(html, d)
        if not rows:
            raise RuntimeError("XSKT: không nhận diện được bảng kết quả")
        return rows, url

    def parse_xskt(self, html, d):
        soup = BeautifulSoup(html, "html.parser")
        best = None

        for table in soup.find_all("table"):
            txt = norm_text(table.get_text(" ", strip=True))
            score = sum(k in txt for k in ["g 8", "g 7", "g 6", "g 5", "g 4", "g 3", "g 2", "g 1"])
            if ("db" in txt or "đb" in table.get_text(" ", strip=True).lower()) and score >= 5:
                if best is None or score > best[0]:
                    best = (score, table)

        if best is None:
            return []

        table = best[1]
        trs = table.find_all("tr")

        # Tìm hàng tiêu đề: thường ô đầu chứa ngày/thứ, các ô sau là tên tỉnh.
        header_cells = None
        for tr in trs[:6]:
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) >= 3:
                names = [c.get_text(" ", strip=True) for c in cells]
                province_hits = sum(
                    1 for x in names[1:]
                    if canonical_province(x) in ALL_PROVINCES
                )
                if province_hits >= 2:
                    header_cells = cells
                    break

        if header_cells is None:
            # Fallback: tìm hàng có >=2 tên tỉnh.
            for tr in trs:
                cells = tr.find_all(["th", "td"])
                if len(cells) >= 3:
                    names = [c.get_text(" ", strip=True) for c in cells]
                    province_hits = sum(1 for x in names[1:] if canonical_province(x) in ALL_PROVINCES)
                    if province_hits >= 2:
                        header_cells = cells
                        break

        if header_cells is None:
            return []

        provinces = [canonical_province(c.get_text(" ", strip=True)) for c in header_cells[1:]]
        provinces = [p if p in ALL_PROVINCES else p for p in provinces]

        out = []
        for tr in trs:
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) < 2:
                continue

            label = cells[0].get_text(" ", strip=True)
            prize = canonical_prize(label)
            if not prize:
                continue

            for idx, cell in enumerate(cells[1:]):
                if idx >= len(provinces):
                    break
                province = provinces[idx]
                nums = numbers_for_prize(cell.get_text(" ", strip=True), prize)
                for n in nums:
                    out.append({"province": province, "prize": prize, "number": n})

        return self.validate_rows(out, d)

    def fetch_minhngoc(self, d):
        urls = [
            f"https://www.minhngoc.net.vn/ket-qua-xo-so/mien-nam/{d.strftime('%d-%m-%Y')}.html",
            f"https://www.minhngoc.net.vn/kqxs/mien-nam/{d.strftime('%d-%m-%Y')}.html",
        ]
        last_error = None
        for url in urls:
            try:
                html = self.get_html(url)
                rows = self.parse_minhngoc(html, d)
                if rows:
                    return rows, url
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Minh Ngọc: không nhận diện được kết quả. {last_error or ''}")

    def parse_minhngoc(self, html, d):
        soup = BeautifulSoup(html, "html.parser")

        # Cách 1: thử các box kết quả theo class.
        rows = []
        boxes = soup.select("div.box_kqxs, div[class*='box_kqxs']")
        for box in boxes:
            box_text = box.get_text(" ", strip=True)
            province = self.detect_province(box_text)
            if not province:
                continue
            for prize in PRIZE_ORDER:
                class_candidates = {
                    "G8": ["giai8"], "G7": ["giai7"], "G6": ["giai6"],
                    "G5": ["giai5"], "G4": ["giai4"], "G3": ["giai3"],
                    "G2": ["giai2"], "G1": ["giai1"], "DB": ["giaidb", "giaiDB"]
                }[prize]
                elem = None
                for cls in class_candidates:
                    elem = box.select_one(f".{cls}")
                    if elem:
                        break
                if elem:
                    for n in numbers_for_prize(elem.get_text(" ", strip=True), prize):
                        rows.append({"province": province, "prize": prize, "number": n})

        valid = self.validate_rows(rows, d)
        if valid:
            return valid

        # Cách 2: parser theo text tuần tự.
        # Cấu trúc công khai của Minh Ngọc thường hiển thị:
        # Tỉnh -> mã vé -> G8 -> G7 -> G6 -> ... -> ĐB.
        text = soup.get_text("\n", strip=True)
        lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
        expected = SOUTH_SCHEDULE.get(d.weekday(), [])

        rows = []
        for province in expected:
            idx = self.find_province_line(lines, province)
            if idx is None:
                continue

            # Cắt block đến tỉnh tiếp theo hoặc tối đa 80 dòng.
            end = min(len(lines), idx + 80)
            for other in expected:
                if other == province:
                    continue
                j = self.find_province_line(lines[idx + 1:end], other)
                if j is not None:
                    end = min(end, idx + 1 + j)

            segment = lines[idx + 1:end]
            tokens = []
            for line in segment:
                tokens.extend(re.findall(r"\b\d+\b", line))

            # Tìm chuỗi 18 kết quả theo đúng pattern độ dài.
            pattern = []
            for p in PRIZE_ORDER:
                pattern.extend([(p, PRIZE_LENGTH[p])] * PRIZE_COUNT[p])

            match = self.match_number_pattern(tokens, pattern)
            if match:
                for prize, number in match:
                    rows.append({"province": province, "prize": prize, "number": number})

        return self.validate_rows(rows, d)

    def detect_province(self, text):
        nt = norm_text(text)
        hits = []
        for p in ALL_PROVINCES:
            if norm_text(p) in nt:
                hits.append(p)
        # Hồ Chí Minh thường hiện TP. HCM
        if any(x in nt for x in ["tp hcm", "tphcm"]):
            hits.append("Hồ Chí Minh")
        return hits[0] if hits else None

    def find_province_line(self, lines, province):
        aliases = MINHNGOC_NAMES.get(province, [province])
        aliases_norm = [norm_text(a) for a in aliases]
        for i, line in enumerate(lines):
            nl = norm_text(line)
            if any(a == nl or a in nl for a in aliases_norm):
                # tránh menu/đường dẫn: ưu tiên dòng ngắn
                if len(line) <= 60:
                    return i
        return None

    def match_number_pattern(self, tokens, pattern):
        # Quét để tìm điểm bắt đầu: token 2 chữ số (G8), sau đó phải khớp
        # lần lượt đúng 18 kết quả. Cho phép bỏ qua token không đúng độ dài
        # rất ít để né mã vé/ngày.
        for start in range(len(tokens)):
            if len(tokens[start]) != 2:
                continue
            out = []
            pos = start
            skips = 0
            ok = True
            for prize, expected_len in pattern:
                found = None
                while pos < len(tokens) and skips <= 6:
                    tok = tokens[pos]
                    pos += 1
                    if len(tok) == expected_len:
                        found = tok
                        break
                    skips += 1
                if found is None:
                    ok = False
                    break
                out.append((prize, found))
            if ok and len(out) == 18:
                return out
        return None

    def validate_rows(self, rows, d):
        if not rows:
            return []

        # Chỉ giữ tỉnh dự kiến của ngày đó nếu nhận diện được.
        expected = set(SOUTH_SCHEDULE.get(d.weekday(), []))
        cleaned = []
        for r in rows:
            p = canonical_province(r["province"])
            prize = r["prize"]
            n = str(r["number"]).strip()
            if p not in expected:
                continue
            if prize not in PRIZE_ORDER:
                continue
            if not (n.isdigit() and len(n) == PRIZE_LENGTH[prize]):
                continue
            cleaned.append({"province": p, "prize": prize, "number": n})

        # Mỗi tỉnh hợp lệ phải có gần đủ 18 kết quả.
        per_prov = Counter(r["province"] for r in cleaned)
        good_prov = {p for p, c in per_prov.items() if c >= 16}
        cleaned = [r for r in cleaned if r["province"] in good_prov]

        # Cần ít nhất 2 tỉnh để coi là trang XSMN hợp lệ.
        if len(good_prov) < 2:
            return []
        return cleaned

    def fetch_auto(self, d, mode="Tự động (XSKT → Minh Ngọc)"):
        errors = []
        if mode.startswith("XSKT"):
            rows, url = self.fetch_xskt(d)
            return rows, "XSKT", url
        if mode.startswith("Minh"):
            rows, url = self.fetch_minhngoc(d)
            return rows, "Minh Ngọc", url

        try:
            rows, url = self.fetch_xskt(d)
            return rows, "XSKT", url
        except Exception as e:
            errors.append(f"XSKT: {e}")

        try:
            rows, url = self.fetch_minhngoc(d)
            return rows, "Minh Ngọc", url
        except Exception as e:
            errors.append(f"Minh Ngọc: {e}")

        raise RuntimeError(" | ".join(errors))


class Analyzer:
    @staticmethod
    def stats(df, start_date, end_date, province):
        if df.empty:
            return pd.DataFrame()

        d = df.copy()
        d["two"] = d["number"].astype(str).str[-2:].str.zfill(2)

        # Một "kỳ" = 1 ngày x 1 tỉnh. Với lọc 1 tỉnh thì chính là ngày tỉnh đó quay.
        sessions = d[["draw_date", "province"]].drop_duplicates()
        session_keys = set(zip(sessions["draw_date"].dt.date, sessions["province"]))
        total_sessions = len(session_keys)
        total_results = len(d)

        counts = d["two"].value_counts().to_dict()

        # Số kỳ có xuất hiện ít nhất 1 lần.
        hit_sessions = (
            d[["draw_date", "province", "two"]]
            .drop_duplicates()
            .groupby("two")
            .size()
            .to_dict()
        )

        last_seen = d.groupby("two")["draw_date"].max().to_dict()

        # Tính số kỳ kể từ lần cuối xuất hiện.
        sessions_sorted = (
            sessions.sort_values(["draw_date", "province"])
            .reset_index(drop=True)
        )

        gap_map = {}
        for num in [f"{i:02d}" for i in range(100)]:
            last = last_seen.get(num)
            if last is None:
                gap_map[num] = total_sessions
                continue
            after = sessions_sorted[sessions_sorted["draw_date"] > last]
            gap_map[num] = len(after)

        def count_window(days):
            cutoff = pd.Timestamp(end_date - timedelta(days=days - 1))
            wd = d[d["draw_date"] >= cutoff]
            return wd["two"].value_counts().to_dict()

        w7 = count_window(7)
        w30 = count_window(30)
        w90 = count_window(90)
        w180 = count_window(180)
        w365 = count_window(365)

        rows = []
        for i in range(100):
            num = f"{i:02d}"
            c = int(counts.get(num, 0))
            hs = int(hit_sessions.get(num, 0))
            freq_pct = (c / total_results * 100) if total_results else 0
            hit_pct = (hs / total_sessions * 100) if total_sessions else 0

            # Z-score tần suất so với p=1% cho từng kết quả 2 số.
            p0 = 0.01
            mean = total_results * p0
            sd = math.sqrt(max(total_results * p0 * (1 - p0), 1e-12))
            z = (c - mean) / sd

            # Điểm "nóng lịch sử": KHÔNG phải xác suất.
            hot_score = (
                w7.get(num, 0) * 4.0 +
                w30.get(num, 0) * 2.0 +
                w90.get(num, 0) * 1.0
            )

            rows.append({
                "Số": num,
                "Số lần": c,
                "Tỷ lệ lịch sử (%)": freq_pct,
                "Kỳ có mặt": hs,
                "Tỷ lệ kỳ có mặt (%)": hit_pct,
                "7 ngày": int(w7.get(num, 0)),
                "30 ngày": int(w30.get(num, 0)),
                "90 ngày": int(w90.get(num, 0)),
                "180 ngày": int(w180.get(num, 0)),
                "365 ngày": int(w365.get(num, 0)),
                "Kỳ chưa ra": int(gap_map.get(num, 0)),
                "Z-score": z,
                "Điểm nóng LS": hot_score,
                "Lần gần nhất": (
                    pd.Timestamp(last_seen[num]).strftime("%d/%m/%Y")
                    if num in last_seen else ""
                ),
            })

        out = pd.DataFrame(rows)
        out = out.sort_values(
            ["Tỷ lệ lịch sử (%)", "Tỷ lệ kỳ có mặt (%)", "Điểm nóng LS", "Kỳ chưa ra"],
            ascending=[False, False, False, True]
        ).reset_index(drop=True)
        out.insert(0, "Hạng LS", range(1, len(out) + 1))
        return out

    @staticmethod
    def backtest(df, lookback_days=30, top_k=10):
        """
        Mỗi phiên (ngày x tỉnh):
        - lấy dữ liệu của CHÍNH TỈNH đó trong lookback_days trước phiên
        - chọn top_k số 2 chữ số xuất hiện nhiều nhất
        - kiểm tra phiên kế tiếp có ít nhất 1 số trong top_k xuất hiện không.
        So sánh baseline lý thuyết gần đúng: xác suất ít nhất 1 hit khi chọn K số
        trong 18 kết quả = 1 - (1-K/100)^18.
        """
        if df.empty:
            return None, pd.DataFrame()

        d = df.copy()
        d["two"] = d["number"].astype(str).str[-2:].str.zfill(2)
        d = d.sort_values(["province", "draw_date"])

        records = []
        for province, gp in d.groupby("province"):
            dates = sorted(gp["draw_date"].dt.normalize().unique())
            for current in dates:
                cur = pd.Timestamp(current)
                hist_start = cur - pd.Timedelta(days=lookback_days)
                hist = gp[(gp["draw_date"] < cur) & (gp["draw_date"] >= hist_start)]
                if len(hist) < 18:
                    continue

                counts = hist["two"].value_counts()
                picks = counts.head(top_k).index.tolist()
                actual = set(gp[gp["draw_date"].dt.normalize() == cur]["two"].tolist())
                hits = sorted(set(picks) & actual)
                records.append({
                    "Ngày": cur.strftime("%d/%m/%Y"),
                    "Tỉnh": province,
                    "Top K": ",".join(picks),
                    "Trúng": ",".join(hits),
                    "Có hit": 1 if hits else 0,
                    "Số hit": len(hits),
                })

        bt = pd.DataFrame(records)
        if bt.empty:
            return None, bt

        observed = bt["Có hit"].mean() * 100
        baseline = (1 - (1 - top_k / 100.0) ** 18) * 100
        summary = {
            "tests": len(bt),
            "observed_hit_pct": observed,
            "baseline_pct": baseline,
            "diff_pp": observed - baseline,
            "total_hits": int(bt["Số hit"].sum()),
        }
        return summary, bt


class LotteryApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1240x820")
        self.root.minsize(1080, 720)

        self.db = LotteryDB()
        self.fetcher = WebFetcher()
        self.stats_df = pd.DataFrame()
        self.backtest_df = pd.DataFrame()
        self.stop_flag = False

        today = date.today()
        self.source_var = tk.StringVar(value="Tự động (XSKT → Minh Ngọc)")
        self.start_var = tk.StringVar(value=(today - timedelta(days=30)).strftime("%d/%m/%Y"))
        self.end_var = tk.StringVar(value=today.strftime("%d/%m/%Y"))
        self.province_var = tk.StringVar(value="Tất cả")
        self.period_var = tk.StringVar(value="30 ngày")
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        self.dbinfo_var = tk.StringVar(value="")
        self.lookback_var = tk.StringVar(value="30")
        self.topk_var = tk.StringVar(value="10")

        self.build_ui()
        self.refresh_db_info()
        self.refresh_provinces()

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass

        header = ttk.Frame(self.root, padding=10)
        header.pack(fill="x")

        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(
            header,
            text="  |  Thống kê lịch sử, không phải dự đoán chắc chắn",
            foreground="#8a4b00"
        ).pack(side="left", padx=8)

        controls = ttk.LabelFrame(self.root, text="Cập nhật dữ liệu", padding=10)
        controls.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(controls, text="Nguồn:").grid(row=0, column=0, padx=4, pady=4)
        source = ttk.Combobox(
            controls, textvariable=self.source_var, state="readonly", width=28,
            values=["Tự động (XSKT → Minh Ngọc)", "XSKT", "Minh Ngọc"]
        )
        source.grid(row=0, column=1, padx=4, pady=4)

        ttk.Label(controls, text="Từ ngày:").grid(row=0, column=2, padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.start_var, width=12).grid(row=0, column=3, padx=4)

        ttk.Label(controls, text="Đến ngày:").grid(row=0, column=4, padx=4)
        ttk.Entry(controls, textvariable=self.end_var, width=12).grid(row=0, column=5, padx=4)

        ttk.Button(controls, text="7 ngày", command=lambda: self.set_period(7)).grid(row=0, column=6, padx=2)
        ttk.Button(controls, text="30 ngày", command=lambda: self.set_period(30)).grid(row=0, column=7, padx=2)
        ttk.Button(controls, text="90 ngày", command=lambda: self.set_period(90)).grid(row=0, column=8, padx=2)
        ttk.Button(controls, text="1 năm", command=lambda: self.set_period(365)).grid(row=0, column=9, padx=2)

        self.update_btn = ttk.Button(controls, text="CẬP NHẬT TỪ WEB", command=self.start_update)
        self.update_btn.grid(row=1, column=0, columnspan=2, padx=4, pady=7, sticky="ew")

        self.stop_btn = ttk.Button(controls, text="Dừng", command=self.stop_update, state="disabled")
        self.stop_btn.grid(row=1, column=2, padx=4)

        self.progress = ttk.Progressbar(controls, mode="determinate", length=420)
        self.progress.grid(row=1, column=3, columnspan=5, padx=4, sticky="ew")

        ttk.Label(controls, textvariable=self.dbinfo_var).grid(row=1, column=8, columnspan=2, padx=4, sticky="e")

        tabs = ttk.Notebook(self.root)
        tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tab_stats = ttk.Frame(tabs)
        self.tab_history = ttk.Frame(tabs)
        self.tab_backtest = ttk.Frame(tabs)
        self.tab_log = ttk.Frame(tabs)

        tabs.add(self.tab_stats, text="Thống kê 00–99")
        tabs.add(self.tab_history, text="Lịch sử")
        tabs.add(self.tab_backtest, text="Backtest")
        tabs.add(self.tab_log, text="Nhật ký")

        self.build_stats_tab()
        self.build_history_tab()
        self.build_backtest_tab()
        self.build_log_tab()

        bottom = ttk.Frame(self.root, padding=(10, 2, 10, 8))
        bottom.pack(fill="x")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        ttk.Label(
            bottom,
            text="Nguồn web có thể thay đổi cấu trúc; nếu parser lỗi, thử nguồn còn lại.",
            foreground="#666"
        ).pack(side="right")

    def build_stats_tab(self):
        top = ttk.Frame(self.tab_stats, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Tỉnh:").pack(side="left")
        self.province_combo = ttk.Combobox(
            top, textvariable=self.province_var, state="readonly", width=22
        )
        self.province_combo.pack(side="left", padx=5)
        self.province_combo.bind("<<ComboboxSelected>>", lambda e: self.run_stats())

        ttk.Label(top, text="Khoảng phân tích:").pack(side="left", padx=(12, 2))
        self.period_combo = ttk.Combobox(
            top, textvariable=self.period_var, state="readonly", width=12,
            values=["7 ngày", "30 ngày", "90 ngày", "180 ngày", "365 ngày", "Tùy chọn"]
        )
        self.period_combo.pack(side="left", padx=4)
        self.period_combo.bind("<<ComboboxSelected>>", lambda e: self.run_stats())

        ttk.Button(top, text="PHÂN TÍCH", command=self.run_stats).pack(side="left", padx=8)
        ttk.Button(top, text="Biểu đồ Top 20", command=self.plot_top20).pack(side="left", padx=4)
        ttk.Button(top, text="Xuất CSV", command=self.export_stats).pack(side="left", padx=4)

        self.summary_var = tk.StringVar(value="Chưa có thống kê.")
        ttk.Label(
            self.tab_stats, textvariable=self.summary_var,
            padding=(10, 4), wraplength=1160, foreground="#333"
        ).pack(fill="x")

        columns = [
            "Hạng LS", "Số", "Số lần", "Tỷ lệ lịch sử (%)",
            "Kỳ có mặt", "Tỷ lệ kỳ có mặt (%)",
            "7 ngày", "30 ngày", "90 ngày",
            "Kỳ chưa ra", "Z-score", "Điểm nóng LS", "Lần gần nhất"
        ]
        frame = ttk.Frame(self.tab_stats, padding=8)
        frame.pack(fill="both", expand=True)

        self.stats_tree = ttk.Treeview(frame, columns=columns, show="headings", height=24)
        widths = {
            "Hạng LS": 65, "Số": 55, "Số lần": 70, "Tỷ lệ lịch sử (%)": 120,
            "Kỳ có mặt": 85, "Tỷ lệ kỳ có mặt (%)": 135,
            "7 ngày": 65, "30 ngày": 70, "90 ngày": 70,
            "Kỳ chưa ra": 85, "Z-score": 75, "Điểm nóng LS": 95,
            "Lần gần nhất": 100
        }
        for c in columns:
            self.stats_tree.heading(c, text=c)
            self.stats_tree.column(c, width=widths.get(c, 90), anchor="center")

        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.stats_tree.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=self.stats_tree.xview)
        self.stats_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self.stats_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.stats_tree.tag_configure("color_1", background="#ffb3b3")
        self.stats_tree.tag_configure("color_2", background="#ffd9b3")
        self.stats_tree.tag_configure("color_3", background="#ffffb3")
        self.stats_tree.tag_configure("color_4", background="#d9ffb3")
        self.stats_tree.tag_configure("color_5", background="#ffffff")

    def build_history_tab(self):
        top = ttk.Frame(self.tab_history, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Làm mới", command=self.refresh_history).pack(side="left")
        ttk.Button(top, text="Xuất CSV", command=self.export_history).pack(side="left", padx=5)

        columns = ["Ngày", "Tỉnh", "Giải", "Số", "2 số cuối", "Nguồn"]
        frame = ttk.Frame(self.tab_history, padding=8)
        frame.pack(fill="both", expand=True)

        self.history_tree = ttk.Treeview(frame, columns=columns, show="headings", height=26)
        for c, w in zip(columns, [100, 130, 70, 110, 90, 90]):
            self.history_tree.heading(c, text=c)
            self.history_tree.column(c, width=w, anchor="center")

        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=ysb.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

    def build_backtest_tab(self):
        top = ttk.Frame(self.tab_backtest, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Cửa sổ lịch sử (ngày):").pack(side="left")
        ttk.Entry(top, textvariable=self.lookback_var, width=7).pack(side="left", padx=4)
        ttk.Label(top, text="Top K số:").pack(side="left", padx=(12, 2))
        ttk.Entry(top, textvariable=self.topk_var, width=6).pack(side="left", padx=4)
        ttk.Button(top, text="CHẠY BACKTEST", command=self.run_backtest).pack(side="left", padx=8)
        ttk.Button(top, text="Xuất CSV", command=self.export_backtest).pack(side="left", padx=4)

        self.bt_summary_var = tk.StringVar(
            value="Backtest dùng dữ liệu cũ để kiểm tra xem chiến lược 'số nóng' có thực sự hơn mức tham chiếu hay không."
        )
        ttk.Label(
            self.tab_backtest, textvariable=self.bt_summary_var,
            padding=(10, 4), wraplength=1150
        ).pack(fill="x")

        columns = ["Ngày", "Tỉnh", "Top K", "Trúng", "Có hit", "Số hit"]
        frame = ttk.Frame(self.tab_backtest, padding=8)
        frame.pack(fill="both", expand=True)

        self.bt_tree = ttk.Treeview(frame, columns=columns, show="headings", height=25)
        widths = {"Ngày": 100, "Tỉnh": 130, "Top K": 430, "Trúng": 180, "Có hit": 80, "Số hit": 70}
        for c in columns:
            self.bt_tree.heading(c, text=c)
            self.bt_tree.column(c, width=widths[c], anchor="center")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.bt_tree.yview)
        self.bt_tree.configure(yscrollcommand=ysb.set)
        self.bt_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

    def build_log_tab(self):
        self.log = tk.Text(self.tab_log, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

    def append_log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {msg}\n")
        self.log.see("end")

    def parse_ui_date(self, s):
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()

    def set_period(self, days):
        end = date.today()
        start = end - timedelta(days=days - 1)
        self.start_var.set(start.strftime("%d/%m/%Y"))
        self.end_var.set(end.strftime("%d/%m/%Y"))
        self.period_var.set(f"{days} ngày" if days != 365 else "365 ngày")

    def start_update(self):
        try:
            start = self.parse_ui_date(self.start_var.get())
            end = self.parse_ui_date(self.end_var.get())
            if start > end:
                raise ValueError("Từ ngày phải <= đến ngày")
            if end > date.today():
                end = date.today()
                self.end_var.set(end.strftime("%d/%m/%Y"))
        except Exception as e:
            messagebox.showerror("Ngày không hợp lệ", str(e))
            return

        self.stop_flag = False
        self.update_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Đang cập nhật...")
        th = threading.Thread(target=self.update_worker, args=(start, end), daemon=True)
        th.start()

    def stop_update(self):
        self.stop_flag = True
        self.status_var.set("Đang yêu cầu dừng...")

    def update_worker(self, start, end):
        try:
            days = []
            cur = start
            while cur <= end:
                days.append(cur)
                cur += timedelta(days=1)

            total = len(days)
            self.root.after(0, lambda: self.progress.configure(maximum=max(total, 1), value=0))

            ok = 0
            skipped = 0
            fail = 0
            for i, d in enumerate(days, start=1):
                if self.stop_flag:
                    break

                # Không tải ngày tương lai.
                if d > date.today():
                    continue

                if self.db.has_day(d):
                    skipped += 1
                    self.root.after(0, lambda dd=d: self.append_log(f"{dd}: đã có dữ liệu, bỏ qua."))
                    self.root.after(0, lambda v=i: self.progress.configure(value=v))
                    continue

                try:
                    rows, source, url = self.fetcher.fetch_auto(d, self.source_var.get())
                    self.db.upsert_results(d, rows, source)
                    ok += 1
                    self.root.after(
                        0,
                        lambda dd=d, s=source, n=len(rows), u=url:
                            self.append_log(f"{dd}: OK {s}, {n} kết quả. {u}")
                    )
                except Exception as e:
                    fail += 1
                    self.db.log_failure(d, self.source_var.get(), str(e))
                    self.root.after(
                        0,
                        lambda dd=d, err=str(e): self.append_log(f"{dd}: LỖI - {err}")
                    )

                self.root.after(0, lambda v=i: self.progress.configure(value=v))
                time.sleep(POLITE_DELAY)

            self.root.after(
                0,
                lambda: self.status_var.set(
                    f"Xong. Mới: {ok} ngày | Đã có: {skipped} | Lỗi: {fail}"
                    + (" | Đã dừng." if self.stop_flag else "")
                )
            )
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Lỗi cập nhật", str(e)))
            self.root.after(0, lambda: self.append_log(traceback.format_exc()))
        finally:
            self.root.after(0, self.after_update)

    def after_update(self):
        self.update_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.refresh_db_info()
        self.refresh_provinces()
        self.run_stats()
        self.refresh_history()

    def refresh_db_info(self):
        mn, mx, count = self.db.database_range()
        if count:
            self.dbinfo_var.set(f"CSDL: {count:,} kết quả | {mn} → {mx}")
        else:
            self.dbinfo_var.set("CSDL đang trống")

    def refresh_provinces(self):
        provinces = self.db.available_provinces()
        vals = ["Tất cả"] + (provinces if provinces else ALL_PROVINCES)
        self.province_combo["values"] = vals
        if self.province_var.get() not in vals:
            self.province_var.set("Tất cả")

    def stats_range(self):
        end = self.parse_ui_date(self.end_var.get())
        period = self.period_var.get()
        if period == "Tùy chọn":
            start = self.parse_ui_date(self.start_var.get())
        else:
            days = int(period.split()[0])
            start = end - timedelta(days=days - 1)
        return start, end

    def run_stats(self):
        try:
            start, end = self.stats_range()
            province = self.province_var.get()
            df = self.db.dataframe(start, end, province)
            stats = Analyzer.stats(df, start, end, province)
            self.stats_df = stats

            for item in self.stats_tree.get_children():
                self.stats_tree.delete(item)

            if stats.empty:
                self.summary_var.set("Không có dữ liệu trong khoảng đã chọn. Hãy bấm CẬP NHẬT TỪ WEB trước.")
                return

            max_val = stats["Tỷ lệ lịch sử (%)"].max() if not stats.empty else 1
            min_val = stats["Tỷ lệ lịch sử (%)"].min() if not stats.empty else 0
            val_range = max_val - min_val if max_val > min_val else 1

            for _, r in stats.iterrows():
                val = r["Tỷ lệ lịch sử (%)"]
                ratio = (val - min_val) / val_range
                
                if ratio >= 0.8:
                    tag = "color_1"
                elif ratio >= 0.6:
                    tag = "color_2"
                elif ratio >= 0.4:
                    tag = "color_3"
                elif ratio >= 0.2:
                    tag = "color_4"
                else:
                    tag = "color_5"

                vals = [
                    int(r["Hạng LS"]), r["Số"], int(r["Số lần"]),
                    f'{r["Tỷ lệ lịch sử (%)"]:.2f}',
                    int(r["Kỳ có mặt"]), f'{r["Tỷ lệ kỳ có mặt (%)"]:.2f}',
                    int(r["7 ngày"]), int(r["30 ngày"]), int(r["90 ngày"]),
                    int(r["Kỳ chưa ra"]), f'{r["Z-score"]:+.2f}',
                    f'{r["Điểm nóng LS"]:.1f}', r["Lần gần nhất"]
                ]
                self.stats_tree.insert("", "end", values=vals, tags=(tag,))

            d = df.copy()
            sessions = len(d[["draw_date", "province"]].drop_duplicates())
            total = len(d)
            top = stats.head(10)
            top_text = ", ".join(f'{r["Số"]} ({int(r["Số lần"])} lần)' for _, r in top.iterrows())

            # Xác suất tham chiếu xuất hiện ít nhất 1 lần trong 18 kết quả/tỉnh.
            baseline_hit = (1 - 0.99 ** 18) * 100
            self.summary_var.set(
                f"{start.strftime('%d/%m/%Y')} → {end.strftime('%d/%m/%Y')} | "
                f"Tỉnh: {province} | {sessions:,} kỳ (ngày×tỉnh) | {total:,} kết quả. "
                f"Top tần suất lịch sử: {top_text}. "
                f"Tham chiếu: một số 2 chữ số có xác suất ~1% cho MỖI kết quả riêng; "
                f"nếu xét 18 giải của 1 tỉnh, xác suất xuất hiện ít nhất 1 lần xấp xỉ {baseline_hit:.2f}% "
                f"(giả định độc lập/đồng đều). 'Điểm nóng LS' chỉ là điểm xếp hạng quá khứ, không phải xác suất kỳ tới."
            )
        except Exception as e:
            messagebox.showerror("Lỗi thống kê", str(e))

    def plot_top20(self):
        if self.stats_df.empty:
            messagebox.showinfo("Chưa có dữ liệu", "Hãy chạy phân tích trước.")
            return
        top = self.stats_df.head(20).sort_values("Số lần", ascending=True)
        plt.figure(figsize=(10, 7))
        plt.barh(top["Số"], top["Số lần"])
        plt.xlabel("Số lần xuất hiện trong khoảng phân tích")
        plt.ylabel("2 số cuối")
        plt.title("Top 20 tần suất lịch sử")
        plt.tight_layout()
        plt.show()

    def refresh_history(self):
        try:
            start = self.parse_ui_date(self.start_var.get())
            end = self.parse_ui_date(self.end_var.get())
            province = self.province_var.get()
            df = self.db.dataframe(start, end, province)
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            if df.empty:
                return

            # Mới nhất trước
            df = df.sort_values(["draw_date", "province"], ascending=[False, True])
            for _, r in df.head(5000).iterrows():
                self.history_tree.insert("", "end", values=[
                    r["draw_date"].strftime("%d/%m/%Y"),
                    r["province"], r["prize"], r["number"],
                    str(r["number"])[-2:].zfill(2), r["source"]
                ])
        except Exception as e:
            messagebox.showerror("Lỗi lịch sử", str(e))

    def run_backtest(self):
        try:
            lookback = int(self.lookback_var.get())
            topk = int(self.topk_var.get())
            if lookback < 7 or lookback > 3650:
                raise ValueError("Cửa sổ lịch sử nên từ 7 đến 3650 ngày.")
            if topk < 1 or topk > 50:
                raise ValueError("Top K nên từ 1 đến 50.")

            start = self.parse_ui_date(self.start_var.get())
            end = self.parse_ui_date(self.end_var.get())
            # Lấy thêm lookback trước start để backtest ngày đầu khoảng chọn.
            fetch_start = start - timedelta(days=lookback)
            province = self.province_var.get()
            df = self.db.dataframe(fetch_start, end, province)

            summary, bt = Analyzer.backtest(df, lookback_days=lookback, top_k=topk)
            if not bt.empty:
                bt_dates = pd.to_datetime(bt["Ngày"], dayfirst=True)
                bt = bt[(bt_dates.dt.date >= start) & (bt_dates.dt.date <= end)].copy()
                if not bt.empty:
                    observed = bt["Có hit"].mean() * 100
                    baseline = (1 - (1 - topk / 100.0) ** 18) * 100
                    summary = {
                        "tests": len(bt),
                        "observed_hit_pct": observed,
                        "baseline_pct": baseline,
                        "diff_pp": observed - baseline,
                        "total_hits": int(bt["Số hit"].sum()),
                    }

            self.backtest_df = bt

            for item in self.bt_tree.get_children():
                self.bt_tree.delete(item)

            if summary is None or bt.empty:
                self.bt_summary_var.set(
                    "Chưa đủ dữ liệu để backtest. Hãy tải nhiều tháng dữ liệu hơn."
                )
                return

            for _, r in bt.sort_values("Ngày", ascending=False).head(5000).iterrows():
                self.bt_tree.insert("", "end", values=[
                    r["Ngày"], r["Tỉnh"], r["Top K"], r["Trúng"],
                    "Có" if int(r["Có hit"]) else "Không", int(r["Số hit"])
                ])

            self.bt_summary_var.set(
                f"Số phiên kiểm tra: {summary['tests']:,}. "
                f"Tỷ lệ phiên có ít nhất 1 hit trong Top {topk}: {summary['observed_hit_pct']:.2f}%. "
                f"Mức tham chiếu lý thuyết gần đúng khi chọn ngẫu nhiên {topk} số trong 18 kết quả: "
                f"{summary['baseline_pct']:.2f}%. Chênh lệch: {summary['diff_pp']:+.2f} điểm %. "
                f"Đây là kiểm tra quá khứ; chênh lệch nhỏ có thể hoàn toàn do ngẫu nhiên và không đảm bảo tương lai."
            )
        except Exception as e:
            messagebox.showerror("Lỗi backtest", str(e))

    def export_stats(self):
        if self.stats_df.empty:
            messagebox.showinfo("Chưa có dữ liệu", "Hãy chạy phân tích trước.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="thong_ke_00_99.csv"
        )
        if path:
            self.stats_df.to_csv(path, index=False, encoding="utf-8-sig")
            messagebox.showinfo("Đã lưu", path)

    def export_history(self):
        try:
            start = self.parse_ui_date(self.start_var.get())
            end = self.parse_ui_date(self.end_var.get())
            df = self.db.dataframe(start, end, self.province_var.get())
            if df.empty:
                messagebox.showinfo("Không có dữ liệu", "Không có lịch sử để xuất.")
                return
            df["two_digit"] = df["number"].astype(str).str[-2:].str.zfill(2)
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                initialfile="lich_su_xo_so.csv"
            )
            if path:
                df.to_csv(path, index=False, encoding="utf-8-sig")
                messagebox.showinfo("Đã lưu", path)
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def export_backtest(self):
        if self.backtest_df.empty:
            messagebox.showinfo("Chưa có dữ liệu", "Hãy chạy backtest trước.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="backtest_so_nong.csv"
        )
        if path:
            self.backtest_df.to_csv(path, index=False, encoding="utf-8-sig")
            messagebox.showinfo("Đã lưu", path)


def main():
    root = tk.Tk()
    app = LotteryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
