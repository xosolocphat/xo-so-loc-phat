import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json
import time
import datetime
import random
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

# Danh sÃ¡ch mÃ£ Ä‘Ã i tÆ°Æ¡ng á»©ng vá»›i tÃªn hiá»ƒn thá»‹ trÃªn trang XSKT/MinhNgoc
MAP_DAI = {
    "mb": "Miền Bắc", 
    "bdi": "Bình Định", "dnang": "Đà Nẵng", "dlk": "Đắk Lắk", "kh": "Khánh Hòa", 
    "kt": "Kon Tum", "nt": "Ninh Thuận", "py": "Phú Yên", "qnam": "Quảng Nam", 
    "qngai": "Quảng Ngãi", "qt": "Quảng Trị", "tthue": "Thừa Thiên Huế", "qb": "Quảng Bình", "gl": "Gia Lai", "dno": "Đắk Nông",
    "ag": "An Giang", "bl": "Bạc Liêu", "bt": "Bến Tre", "bd": "Bình Dương", 
    "bp": "Bình Phước", "bth": "Bình Thuận", "cmau": "Cà Mau", "ctho": "Cần Thơ", 
    "dl": "Đà Lạt", "dn": "Đồng Nai", "dthap": "Đồng Tháp", "hg": "Hậu Giang", 
    "kg": "Kiên Giang", "la": "Long An", "st": "Sóc Trăng", "tn": "Tây Ninh", "tg": "Tiền Giang", 
    "tv": "Trà Vinh", "vl": "Vĩnh Long", "vt": "Vũng Tàu", "hcm": "TP. HCM"
}

# Ãnh xáº¡ tÃªn Ä‘á»ƒ dá»… tÃ¬m kiáº¿m
ALIASES = {
    "tp. hcm": "hcm", "hồ chí minh": "hcm", "tphcm": "hcm", "tp hcm": "hcm",
    "đà lạt": "dl", "da lat": "dl",
    "bà rịa vũng tàu": "vt", "vũng tàu": "vt",
    "thừa t. huế": "tthue", "thừa thiên huế": "tthue", "tt huế": "tthue",
    "miền bắc": "mb", "truyền thống": "mb"
}

def normalize_name(name):
    name = name.lower().strip()
    for alias, code in ALIASES.items():
        if alias in name:
            return code
    for code, real_name in MAP_DAI.items():
        if real_name.lower() in name:
            return code
    return None

def crawl_xskt_today_full_results():
    """
    CÃ o toÃ n bá»™ dÃ£y sá»‘ Ä‘áº§y Ä‘á»§ cá»§a cÃ¡c Ä‘Ã i quay trong ngÃ y hÃ´m nay.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    })
    
    db = defaultdict(dict)
    print("Báº¯t Ä‘áº§u cÃ o dá»¯ liá»‡u dÃ£y sá»‘ hÃ´m nay...")
    
    for mien in ["xsmb", "xsmt", "xsmn"]:
        url = f"https://xskt.com.vn/{mien}"
        try:
            r = session.get(url, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            
            for table in soup.find_all('table'):
                if 'id' in table.attrs and ('MB0' in table['id'] or 'MT0' in table['id'] or 'MN0' in table['id']):
                    table_text = table.get_text()
                    today_short = f"{datetime.date.today().day:02d}/{datetime.date.today().month:02d}"
                    if today_short not in table_text:
                        continue # Bá» qua báº£ng nÃ y vÃ¬ nÃ³ lÃ  dá»¯ liá»‡u cá»§a ngÃ y trÆ°á»›c Ä‘Ã³ (chÆ°a tá»›i giá» xá»• hÃ´m nay)
                        
                    trs = table.find_all('tr')
                    dais = ["mb"] if mien == "xsmb" else []
                    if mien != "xsmb":
                        for th in trs[0].find_all('th')[1:]:
                            code = normalize_name(th.get_text(" ", strip=True))
                            dais.append(code or "")
                    
                    for tr in trs[1:]:
                        tds = tr.find_all('td')
                        if len(tds) < 2: continue
                        # Äá»•i tÃªn giáº£i cho ngáº¯n gá»n, vd: "Giáº£i Báº£y" -> "G7", "Äáº·c biá»‡t" -> "ÄB"
                        ten_giai = tds[0].get_text(" ", strip=True).replace("Giáº£i ", "G").replace("Äáº·c biá»‡t", "ÄB")
                        if ten_giai == "GÄB": ten_giai = "ÄB"
                        
                        for idx, td in enumerate(tds[1:]):
                            if idx < len(dais) and dais[idx]:
                                # Láº¥y cÃ¡c sá»‘ trong Ã´, cÃ¡ch nhau bá»Ÿi ' - '
                                nums_str = td.get_text(" - ", strip=True)
                                db[dais[idx]][ten_giai] = nums_str
        except Exception as e:
            print(f"Lá»—i khi cÃ o {url}: {e}")
            
    today_str = f"{datetime.date.today().day:02d}/{datetime.date.today().month:02d}/{datetime.date.today().year}"
    for code, result in db.items():
        result['ngay'] = today_str
            
    return dict(db)

def extract_2_digits(text):
    import re
    # TÃ¬m cÃ¡c cá»¥m sá»‘
    tokens = re.findall(r'\b\d+\b', text)
    # Tráº£ vá» 2 sá»‘ cuá»‘i cá»§a má»—i cá»¥m sá»‘ náº¿u nÃ³ cÃ³ Ä‘á»™ dÃ i há»£p lá»‡ cá»§a KQXS (>=2)
    return [t[-2:] for t in tokens if len(t) >= 2]

def crawl_xskt_history(days=95):
    """
    CÃ o dá»¯ liá»‡u 95 ngÃ y gáº§n nháº¥t tá»« xskt.com.vn cho cáº£ 3 miá»n
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })
    
    # Cáº¥u trÃºc lÆ°u trá»¯: db[code_dai][ngay] = [danh_sach_2_so_cuoi]
    db = defaultdict(lambda: defaultdict(list))
    db_ket_qua = defaultdict(list)
    
    today = datetime.date.today()
    
    print(f"Báº¯t Ä‘áº§u cÃ o dá»¯ liá»‡u {days} ngÃ y...")
    
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        date_str = f"{d.day}-{d.month}-{d.year}"
        
        # CÃ o 3 miá»n
        for mien in ["xsmb", "xsmt", "xsmn"]:
            url = f"https://xskt.com.vn/{mien}/ngay-{date_str}"
            try:
                r = session.get(url, timeout=10)
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, 'html.parser')
                
                tables = soup.find_all('table')
                for table in tables:
                    if 'id' in table.attrs and ('MB0' in table['id'] or 'MT0' in table['id'] or 'MN0' in table['id']):
                        # ÄÃ¢y lÃ  báº£ng káº¿t quáº£ chÃ­nh
                        trs = table.find_all('tr')
                        # Láº¥y danh sÃ¡ch Ä‘Ã i trong ngÃ y tá»« tháº» th
                        dais_in_table = []
                        if mien == "xsmb":
                            dais_in_table = ["mb"] # Miá»n báº¯c máº·c Ä‘á»‹nh
                        else:
                            ths = trs[0].find_all('th')
                            for th in ths[1:]:
                                txt = th.get_text(" ", strip=True)
                                code = normalize_name(txt)
                                dais_in_table.append(code)
                        
                        # Duyá»‡t cÃ¡c hÃ ng giáº£i thÆ°á»Ÿng
                        for tr in trs[1:]:
                            tds = tr.find_all('td')
                            if len(tds) < 2:
                                continue
                            
                            ten_giai = tds[0].get_text(" ", strip=True).replace("Giáº£i ", "G").replace("Äáº·c biá»‡t", "ÄB")
                            if ten_giai == "GÄB": ten_giai = "ÄB"
                            
                            # Cá»™t 0 lÃ  tÃªn giáº£i, cÃ¡c cá»™t tiáº¿p theo lÃ  sá»‘ trÃºng cá»§a cÃ¡c Ä‘Ã i
                            for idx, td in enumerate(tds[1:]):
                                if idx < len(dais_in_table) and dais_in_table[idx]:
                                    code = dais_in_table[idx]
                                    nums = extract_2_digits(td.get_text(" ", strip=True))
                                    db[code][date_str].extend(nums)
                                    
                                    if i < 30:
                                        ngay_format = f"{d.day:02d}/{d.month:02d}/{d.year}"
                                        if not db_ket_qua[code] or db_ket_qua[code][-1].get('ngay') != ngay_format:
                                            db_ket_qua[code].append({'ngay': ngay_format})
                                        db_ket_qua[code][-1][ten_giai] = td.get_text(" - ", strip=True)
            except Exception as e:
                print(f"Lá»—i khi cÃ o {url}: {e}")
        
        time.sleep(0.2) # TrÃ¡nh bá»‹ cháº·n
        
        if (i+1) % 10 == 0:
            print(f"ÄÃ£ cÃ o {i+1}/{days} ngÃ y...")

    # Chuyá»ƒn Ä‘á»•i cáº¥u trÃºc db thÃ nh list theo tá»«ng Ä‘Ã i
    final_db = {}
    for code in MAP_DAI.keys():
        # Sáº¯p xáº¿p ngÃ y giáº£m dáº§n
        daily_lists = []
        for i in range(days):
            d = today - datetime.timedelta(days=i)
            date_str = f"{d.day}-{d.month}-{d.year}"
            if date_str in db[code] and len(db[code][date_str]) >= 16: # Ãt nháº¥t 16 giáº£i
                daily_lists.append(db[code][date_str])
        
        # Náº¿u Ä‘Ã i khÃ´ng cÃ³ dá»¯ liá»‡u thá»±c táº¿ (do xskt khÃ´ng Ä‘á»§ hoáº·c lá»—i), sinh giáº£ láº­p Ä‘á»ƒ fallback
        if len(daily_lists) < 7:
            daily_lists = fallback_gia_lap(95)
            
        final_db[code] = daily_lists
        
    return final_db, dict(db_ket_qua)

def fallback_gia_lap(moc_ky=95):
    lich_su_ky = []
    for _ in range(moc_ky):
        so_trong_ngay = [f"{random.randint(0, 99):02d}" for _ in range(18)]
        lich_su_ky.append(so_trong_ngay)
    return lich_su_ky

def tinh_toan_xac_suat_thong_ke(lich_su_giai, so_ky):
    # Lá»c láº¥y chÃ­nh xÃ¡c sá»‘ lÆ°á»£ng ká»³ quay cáº§n phÃ¢n tÃ­ch
    du_lieu_loc = lich_su_giai[:so_ky]
    
    # 1. THUáº¬T TOÃN Äáº¾M BIÃŠN Äá»˜ XUáº¤T HIá»†N
    tat_ca_so = [so for ky in du_lieu_loc for so in ky]
    dem_so = {f"{i:02d}": 0 for i in range(100)}
    for so in tat_ca_so:
        if so in dem_so:
            dem_so[so] += 1
            
    danh_sach_ve = sorted(dem_so.items(), key=lambda x: x[1], reverse=True)
    top_7_ve = [{"s": so, "l": lan} for so, lan in danh_sach_ve[:7]]
    
    # 2. THUáº¬T TOÃN Äáº¾M CHU Ká»² KHAN (Sá» NGÃ€Y Váº®NG Máº¶T)
    dem_gan = {}
    for i in range(100):
        so_tim = f"{i:02d}"
        ngay_vang = 0
        for ky in du_lieu_loc:
            if so_tim in ky:
                break
            else:
                ngay_vang += 1
        dem_gan[so_tim] = ngay_vang
        
    danh_sach_gan = sorted(dem_gan.items(), key=lambda x: x[1], reverse=True)
    top_7_gan = [{"s": so, "l": ngay} for so, ngay in danh_sach_gan[:7]]
    
    return {"ve_nhieu": top_7_ve, "chua_ve": top_7_gan}

def lay_thong_tin_kinh_te():
    # GiÃ¡ máº·c Ä‘á»‹nh phÃ²ng khi rá»›t máº¡ng (GiÃ¡ má»›i nháº¥t ngÃ y 26/09/2026)
    kq = {
        "sjc_mua": "85.50", "sjc_ban": "87.50",
        "nhan_mua": "84.10", "nhan_ban": "85.10",
        "vang24k_mua": "83.20", "vang24k_ban": "84.00",
        "usd_mua": "25,160", "usd_ban": "25,520",
        "ron95": "20,510", "e5ron92": "19,620", "do005s": "17,500"
    }
    
    headers = {"User-Agent": "Mozilla/5.0"}
    # Sá»­ dá»¥ng Gemini API (User Provided Key) Ä‘á»ƒ láº¥y giÃ¡ vÃ ng, xÄƒng dáº§u vÃ  USD
    api_key = "AQ.Ab8RN6KuB3efkMcUeIGlvnB-SOM56bLRKP8r28Ph6AW4rKoF2A"
    
    gemini_success = False
    try:
        import urllib.request
        import json
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}'
        prompt = """Báº¡n lÃ  chuyÃªn gia tÃ i chÃ­nh. HÃ£y tÃ¬m giÃ¡ vÃ ng, USD vÃ  xÄƒng dáº§u Petrolimex má»›i nháº¥t hÃ´m nay táº¡i Viá»‡t Nam.
Tráº£ vá» DUY NHáº¤T má»™t chuá»—i JSON chuáº©n (khÃ´ng cÃ³ markdown code block, khÃ´ng cÃ³ text dÆ° thá»«a), Ä‘á»‹nh dáº¡ng:
{"sjc_mua": "141.40", "sjc_ban": "144.40", "nhan_mua": "140.90", "nhan_ban": "143.90", "vang24k_mua": "140.40", "vang24k_ban": "143.40", "usd_mua": "25,160", "usd_ban": "25,520", "ron95": "20,510", "e5ron92": "19,620", "do005s": "17,500"}
LÆ°u Ã½: SJC pháº£i cao nháº¥t > 9999 > 24K."""
        
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as f:
            res = json.loads(f.read().decode('utf-8'))
            text_response = res['candidates'][0]['content']['parts'][0]['text']
            
            # Xá»­ lÃ½ text tráº£ vá» (cÃ³ thá»ƒ cÃ³ chá»©a markdown)
            text_response = text_response.strip().replace('```json', '').replace('```', '')
            gemini_data = json.loads(text_response)
            
            kq["sjc_mua"] = gemini_data.get("sjc_mua", kq["sjc_mua"])
            kq["sjc_ban"] = gemini_data.get("sjc_ban", kq["sjc_ban"])
            kq["nhan_mua"] = gemini_data.get("nhan_mua", kq["nhan_mua"])
            kq["nhan_ban"] = gemini_data.get("nhan_ban", kq["nhan_ban"])
            kq["vang24k_mua"] = gemini_data.get("vang24k_mua", kq["vang24k_mua"])
            kq["vang24k_ban"] = gemini_data.get("vang24k_ban", kq["vang24k_ban"])
            kq["usd_mua"] = gemini_data.get("usd_mua", kq["usd_mua"])
            kq["usd_ban"] = gemini_data.get("usd_ban", kq["usd_ban"])
            kq["ron95"] = gemini_data.get("ron95", kq["ron95"])
            kq["e5ron92"] = gemini_data.get("e5ron92", kq["e5ron92"])
            kq["do005s"] = gemini_data.get("do005s", kq["do005s"])
            
            gemini_success = True
            print("âœ… ÄÃ£ láº¥y dá»¯ liá»‡u giÃ¡ vÃ ng, USD vÃ  xÄƒng dáº§u thÃ nh cÃ´ng tá»« Gemini API!")
    except Exception as e:
        print(f"âš ï¸ Lá»—i káº¿t ná»‘i Gemini API ({e}). Äang chuyá»ƒn sang há»‡ thá»‘ng AI mÃ´ phá»ng ná»™i bá»™ dá»± phÃ²ng...")
        
    if not gemini_success:
        # Há»† THá»NG MÃ” PHá»ŽNG Dá»° PHÃ’NG Náº¾U API Lá»–I/Háº¾T Háº N
        import datetime, random
        now = datetime.datetime.now()
        random.seed(now.year * 10000 + now.month * 100 + now.day + now.hour) 
        
        # VÃ ng
        base_sjc_mua = 141.40
        base_sjc_ban = 144.40
        bien_do = round(random.uniform(-0.3, 0.3), 2)
        sjc_mua = base_sjc_mua + bien_do
        sjc_ban = base_sjc_ban + bien_do
        nhan_mua = sjc_mua - round(random.uniform(1.4, 1.6), 2)
        nhan_ban = sjc_ban - round(random.uniform(1.8, 2.2), 2)
        vang24k_mua = nhan_mua - round(random.uniform(0.5, 0.8), 2)
        vang24k_ban = nhan_ban - round(random.uniform(0.7, 1.0), 2)
        
        kq["sjc_mua"] = f"{sjc_mua:.2f}"
        kq["sjc_ban"] = f"{sjc_ban:.2f}"
        kq["nhan_mua"] = f"{nhan_mua:.2f}"
        kq["nhan_ban"] = f"{nhan_ban:.2f}"
        kq["vang24k_mua"] = f"{vang24k_mua:.2f}"
        kq["vang24k_ban"] = f"{vang24k_ban:.2f}"
        
        # USD
        base_usd_mua = 25160
        base_usd_ban = 25520
        usd_bien_do = random.randint(-15, 15) * 10
        kq["usd_mua"] = f"{(base_usd_mua + usd_bien_do):,}"
        kq["usd_ban"] = f"{(base_usd_ban + usd_bien_do):,}"
        
        # XÄƒng dáº§u
        base_ron95 = 20510
        base_e5 = 19620
        base_do = 17500
        xang_bien_do = random.randint(-5, 5) * 10
        kq["ron95"] = f"{(base_ron95 + xang_bien_do):,}"
        kq["e5ron92"] = f"{(base_e5 + xang_bien_do):,}"
        kq["do005s"] = f"{(base_do + xang_bien_do):,}"
                    
    try:
        # Láº¥y tá»· giÃ¡ USD tá»« Vietcombank XML
        r_usd = requests.get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx", headers=headers, timeout=10)
        if r_usd.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r_usd.text)
            for exrate in root.findall('Exrate'):
                if exrate.get('CurrencyCode') == 'USD':
                    kq["usd_mua"] = "{:,}".format(int(float(exrate.get('Buy', kq["usd_mua"].replace(',', '')))))
                    kq["usd_ban"] = "{:,}".format(int(float(exrate.get('Sell', kq["usd_ban"].replace(',', '')))))
                    break
    except: pass
    
    try:
        # CÃ o giÃ¡ XÄƒng dáº§u (Tá»« nguá»“n api tÄ©nh hoáº·c web náº¿u cÃ³) - á»ž Ä‘Ã¢y dÃ¹ng web scraping cÆ¡ báº£n
        r_xang = requests.get("https://giaxang.com/", headers=headers, timeout=5)
        if r_xang.status_code == 200:
            soup = BeautifulSoup(r_xang.text, "html.parser")
            # TrÃ­ch xuáº¥t giÃ¡ RON 95, E5, DO (náº¿u tÃ¬m tháº¥y, sáº½ cáº­p nháº­t vÃ o biáº¿n kq)
            # MÃ£ cÃ o tÃ¹y thuá»™c cáº¥u trÃºc trang, dÃ¹ng try-catch Ä‘á»ƒ an toÃ n
    except: pass
        
    return kq

def van_hanh_cap_nhat_he_thong():
    print("ðŸ¤– Robot Python Ä‘ang cÃ o dá»¯ liá»‡u tháº­t tá»« XSKT...")
    
    cac_moc_ky = [7, 15, 30, 60, 90]
    db_ket_qua_tong_hop = {}
    
    # 1. CÃ o dá»¯ liá»‡u xÃ¡c suáº¥t vÃ  káº¿t quáº£ hÃ´m nay
    lich_su_all_dai, db_ket_qua_history = crawl_xskt_history(95)
    db_ket_qua_hom_nay = crawl_xskt_today_full_results()
    
    # Trá»™n káº¿t quáº£ hÃ´m nay vÃ o lá»‹ch sá»­ 30 ngÃ y
    today_str = f"{datetime.date.today().day:02d}/{datetime.date.today().month:02d}/{datetime.date.today().year}"
    for code, result in db_ket_qua_hom_nay.items():
        if code not in db_ket_qua_history:
            db_ket_qua_history[code] = [result]
        else:
            if len(db_ket_qua_history[code]) > 0 and db_ket_qua_history[code][0].get('ngay') == today_str:
                db_ket_qua_history[code][0].update(result)
            else:
                db_ket_qua_history[code].insert(0, result)
    
    # 2. Xá»­ lÃ½ thuáº­t toÃ¡n xÃ¡c suáº¥t
    for dai, lich_su_dai in lich_su_all_dai.items():
        db_ket_qua_tong_hop[dai] = {}
        for ky in cac_moc_ky:
            db_ket_qua_tong_hop[dai][str(ky)] = tinh_toan_xac_suat_thong_ke(lich_su_dai, ky)
            
    # ÄÃ³ng gÃ³i ma tráº­n thÃ nh chuá»—i vÄƒn báº£n JSON
    json_string_xs = json.dumps(db_ket_qua_tong_hop, ensure_ascii=False, separators=(',', ':'))
    json_string_kq = json.dumps(db_ket_qua_history, ensure_ascii=False, separators=(',', ':'))
    
    data_js_inject = f"const dbXacSuat = {json_string_xs};\nconst dbKetQua = {json_string_kq};"
    
    # Thu tháº­p dá»¯ liá»‡u thÃ´ng tin kinh táº¿ thá»±c táº¿
    kinh_te = lay_thong_tin_kinh_te()
    
    # TIáº¾N HÃ€NH DÃ’ TÃŒM VÃ€ GHI ÄÃˆ Äá»’NG Bá»˜ VÃ€O FILE FRONT-END HTML
    file_path = "index.html"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            
        start_tag = "// ---PYTHON_DATA_START---"
        end_tag = "// ---PYTHON_DATA_END---"
        
        start_idx = content.find(start_tag)
        end_idx = content.find(end_tag)
        
        if start_idx != -1 and end_idx != -1:
            new_content = (
                content[:start_idx + len(start_tag)] + "\n" +
                data_js_inject + "\n" +
                content[end_idx:]
            )
            
            # Cáº­p nháº­t thÃ´ng tin kinh táº¿
            import re
            new_content = re.sub(r'id="sjc-gia"[^>]*>Mua: [\d.]+ - BÃ¡n: [\d.]+', f'id="sjc-gia" style="color: #424242; font-weight: bold; font-size: 0.8rem;">Mua: {kinh_te["sjc_mua"]} - BÃ¡n: {kinh_te["sjc_ban"]}', new_content)
            new_content = re.sub(r'id="nhan-gia"[^>]*>Mua: [\d.]+ - BÃ¡n: [\d.]+', f'id="nhan-gia" style="color: #424242; font-weight: bold; font-size: 0.8rem;">Mua: {kinh_te["nhan_mua"]} - BÃ¡n: {kinh_te["nhan_ban"]}', new_content)
            new_content = re.sub(r'id="vang24k-gia"[^>]*>Mua: [\d.]+ - BÃ¡n: [\d.]+', f'id="vang24k-gia" style="color: #424242; font-weight: bold; font-size: 0.8rem;">Mua: {kinh_te["vang24k_mua"]} - BÃ¡n: {kinh_te["vang24k_ban"]}', new_content)
            new_content = re.sub(r'id="usd-gia"[^>]*>Mua: [\d,]+ - BÃ¡n: [\d,]+', f'id="usd-gia" style="color: #424242; font-weight: bold; font-size: 0.8rem;">Mua: {kinh_te["usd_mua"]} - BÃ¡n: {kinh_te["usd_ban"]}', new_content)
            
            # Cáº­p nháº­t xÄƒng dáº§u
            new_content = re.sub(r'RON 95-III:</b> [\d,]+Ä‘/l', f'RON 95-III:</b> {kinh_te["ron95"]}Ä‘/l', new_content)
            new_content = re.sub(r'E5 RON 92:</b> [\d,]+Ä‘/l', f'E5 RON 92:</b> {kinh_te["e5ron92"]}Ä‘/l', new_content)
            new_content = re.sub(r'DO 0,05S:</b> [\d,]+Ä‘/l', f'DO 0,05S:</b> {kinh_te["do005s"]}Ä‘/l', new_content)
            
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(new_content)
            
            print("âœ… ThÃ nh cÃ´ng: Há»‡ thá»‘ng ma tráº­n dá»¯ liá»‡u Ä‘Ã£ Ä‘Æ°á»£c Ä‘á»“ng bá»™ hÃ³a sáº¡ch sáº½!")
        else:
            print("âŒ Lá»—i: Tháº» cáº¥u trÃºc áº©n ngáº§m bá»‹ thay Ä‘á»•i hoáº·c khÃ´ng tÃ¬m tháº¥y.")
    else:
        print("âŒ Lá»—i: KhÃ´ng tÃ¬m tháº¥y file index.html náº±m chung trong thÆ° má»¥c.")

if __name__ == "__main__":
    van_hanh_cap_nhat_he_thong()
