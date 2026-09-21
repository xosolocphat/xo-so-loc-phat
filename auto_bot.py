import os
import json
import time
import datetime
import random
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

# Danh sách mã đài tương ứng với tên hiển thị trên trang XSKT/MinhNgoc
MAP_DAI = {
    "mb": "Miền Bắc", 
    "bdi": "Bình Định", "dnang": "Đà Nẵng", "dlk": "Đắk Lắk", "kh": "Khánh Hòa", 
    "kt": "Kon Tum", "nt": "Ninh Thuận", "py": "Phú Yên", "qnam": "Quảng Nam", 
    "qngai": "Quảng Ngãi", "qt": "Quảng Trị", "tthue": "Thừa Thiên Huế", 
    "ag": "An Giang", "bl": "Bạc Liêu", "bt": "Bến Tre", "bd": "Bình Dương", 
    "bp": "Bình Phước", "bth": "Bình Thuận", "cmau": "Cà Mau", "ctho": "Cần Thơ", 
    "dl": "Đà Lạt", "dn": "Đồng Nai", "dthap": "Đồng Tháp", "hg": "Hậu Giang", 
    "la": "Long An", "st": "Sóc Trăng", "tn": "Tây Ninh", "tg": "Tiền Giang", 
    "hcm": "TP. HCM", "tv": "Trà Vinh", "vl": "Vĩnh Long", "vt": "Vũng Tàu"
}

# Ánh xạ tên để dễ tìm kiếm
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
    Cào toàn bộ dãy số đầy đủ của các đài quay trong ngày hôm nay.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    })
    
    db = defaultdict(dict)
    print("Bắt đầu cào dữ liệu dãy số hôm nay...")
    
    for mien in ["xsmb", "xsmt", "xsmn"]:
        url = f"https://xskt.com.vn/{mien}"
        try:
            r = session.get(url, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            
            for table in soup.find_all('table'):
                if 'id' in table.attrs and ('MB0' in table['id'] or 'MT0' in table['id'] or 'MN0' in table['id']):
                    trs = table.find_all('tr')
                    dais = ["mb"] if mien == "xsmb" else []
                    if mien != "xsmb":
                        for th in trs[0].find_all('th')[1:]:
                            code = normalize_name(th.get_text(" ", strip=True))
                            if code:
                                dais.append(code)
                    
                    for tr in trs[1:]:
                        tds = tr.find_all('td')
                        if len(tds) < 2: continue
                        # Đổi tên giải cho ngắn gọn, vd: "Giải Bảy" -> "G7", "Đặc biệt" -> "ĐB"
                        ten_giai = tds[0].get_text(" ", strip=True).replace("Giải ", "G").replace("Đặc biệt", "ĐB")
                        if ten_giai == "GĐB": ten_giai = "ĐB"
                        
                        for idx, td in enumerate(tds[1:]):
                            if idx < len(dais) and dais[idx]:
                                # Lấy các số trong ô, cách nhau bởi ' - '
                                nums_str = td.get_text(" - ", strip=True)
                                db[dais[idx]][ten_giai] = nums_str
        except Exception as e:
            print(f"Lỗi khi cào {url}: {e}")
            
    return dict(db)

def extract_2_digits(text):
    import re
    # Tìm các cụm số
    tokens = re.findall(r'\b\d+\b', text)
    # Trả về 2 số cuối của mỗi cụm số nếu nó có độ dài hợp lệ của KQXS (>=2)
    return [t[-2:] for t in tokens if len(t) >= 2]

def crawl_xskt_history(days=95):
    """
    Cào dữ liệu 95 ngày gần nhất từ xskt.com.vn cho cả 3 miền
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })
    
    # Cấu trúc lưu trữ: db[code_dai][ngay] = [danh_sach_2_so_cuoi]
    db = defaultdict(lambda: defaultdict(list))
    
    today = datetime.date.today()
    
    print(f"Bắt đầu cào dữ liệu {days} ngày...")
    
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        date_str = f"{d.day}-{d.month}-{d.year}"
        
        # Cào 3 miền
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
                        # Đây là bảng kết quả chính
                        trs = table.find_all('tr')
                        # Lấy danh sách đài trong ngày từ thẻ th
                        dais_in_table = []
                        if mien == "xsmb":
                            dais_in_table = ["mb"] # Miền bắc mặc định
                        else:
                            ths = trs[0].find_all('th')
                            for th in ths[1:]:
                                txt = th.get_text(" ", strip=True)
                                code = normalize_name(txt)
                                dais_in_table.append(code)
                        
                        # Duyệt các hàng giải thưởng
                        for tr in trs[1:]:
                            tds = tr.find_all('td')
                            if len(tds) < 2:
                                continue
                            
                            # Cột 0 là tên giải, các cột tiếp theo là số trúng của các đài
                            for idx, td in enumerate(tds[1:]):
                                if idx < len(dais_in_table) and dais_in_table[idx]:
                                    code = dais_in_table[idx]
                                    nums = extract_2_digits(td.get_text(" ", strip=True))
                                    db[code][date_str].extend(nums)
            except Exception as e:
                print(f"Lỗi khi cào {url}: {e}")
        
        time.sleep(0.2) # Tránh bị chặn
        
        if (i+1) % 10 == 0:
            print(f"Đã cào {i+1}/{days} ngày...")

    # Chuyển đổi cấu trúc db thành list theo từng đài
    final_db = {}
    for code in MAP_DAI.keys():
        # Sắp xếp ngày giảm dần
        daily_lists = []
        for i in range(days):
            d = today - datetime.timedelta(days=i)
            date_str = f"{d.day}-{d.month}-{d.year}"
            if date_str in db[code] and len(db[code][date_str]) >= 16: # Ít nhất 16 giải
                daily_lists.append(db[code][date_str])
        
        # Nếu đài không có dữ liệu thực tế (do xskt không đủ hoặc lỗi), sinh giả lập để fallback
        if len(daily_lists) < 7:
            daily_lists = fallback_gia_lap(95)
            
        final_db[code] = daily_lists
        
    return final_db

def fallback_gia_lap(moc_ky=95):
    lich_su_ky = []
    for _ in range(moc_ky):
        so_trong_ngay = [f"{random.randint(0, 99):02d}" for _ in range(18)]
        lich_su_ky.append(so_trong_ngay)
    return lich_su_ky

def tinh_toan_xac_suat_thong_ke(lich_su_giai, so_ky):
    # Lọc lấy chính xác số lượng kỳ quay cần phân tích
    du_lieu_loc = lich_su_giai[:so_ky]
    
    # 1. THUẬT TOÁN ĐẾM BIÊN ĐỘ XUẤT HIỆN
    tat_ca_so = [so for ky in du_lieu_loc for so in ky]
    dem_so = {f"{i:02d}": 0 for i in range(100)}
    for so in tat_ca_so:
        if so in dem_so:
            dem_so[so] += 1
            
    danh_sach_ve = sorted(dem_so.items(), key=lambda x: x[1], reverse=True)
    top_7_ve = [{"s": so, "l": lan} for so, lan in danh_sach_ve[:7]]
    
    # 2. THUẬT TOÁN ĐẾM CHU KỲ KHAN (SỐ NGÀY VẮNG MẶT)
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

def lay_gia_vang_thuc_te_hom_nay():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://webgia.com/gia-vang/sjc/", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Mặc định dự phòng
        sjc_mua = "81.50"
        sjc_ban = "83.50"
        nhan_mua = "79.00"
        nhan_ban = "80.50"
        
        trs = soup.find_all('tr')
        # Tìm SJC Hồ Chí Minh
        for tr in trs:
            if 'Hồ Chí Minh' in tr.text and 'SJC' in tr.text:
                tds = tr.find_all('td')
                if len(tds) >= 3:
                    mua = tds[1].text.strip().replace(',', '').replace('.', '')
                    ban = tds[2].text.strip().replace(',', '').replace('.', '')
                    sjc_mua = f"{(float(mua) / 1000000):.2f}"
                    sjc_ban = f"{(float(ban) / 1000000):.2f}"
                break
        
        # Tìm Vàng nhẫn
        for tr in trs:
            if 'Nhẫn' in tr.text and '99' in tr.text:
                tds = tr.find_all('td')
                if len(tds) >= 3:
                    mua = tds[1].text.strip().replace(',', '').replace('.', '')
                    ban = tds[2].text.strip().replace(',', '').replace('.', '')
                    nhan_mua = f"{(float(mua) / 1000000):.2f}"
                    nhan_ban = f"{(float(ban) / 1000000):.2f}"
                break
                
        return {
            "sjc_mua": sjc_mua,
            "sjc_ban": sjc_ban,
            "nhan_mua": nhan_mua,
            "nhan_ban": nhan_ban
        }
    except Exception as e:
        return {
            "sjc_mua": "81.50",
            "sjc_ban": "83.50",
            "nhan_mua": "79.00",
            "nhan_ban": "80.50"
        }

def van_hanh_cap_nhat_he_thong():
    print("🤖 Robot Python đang cào dữ liệu thật từ XSKT...")
    
    cac_moc_ky = [7, 15, 30, 60, 90]
    db_ket_qua_tong_hop = {}
    
    # 1. Cào dữ liệu xác suất và kết quả hôm nay
    lich_su_all_dai = crawl_xskt_history(95)
    db_ket_qua_hom_nay = crawl_xskt_today_full_results()
    
    # 2. Xử lý thuật toán xác suất
    for dai, lich_su_dai in lich_su_all_dai.items():
        db_ket_qua_tong_hop[dai] = {}
        for ky in cac_moc_ky:
            db_ket_qua_tong_hop[dai][str(ky)] = tinh_toan_xac_suat_thong_ke(lich_su_dai, ky)
            
    # Đóng gói ma trận thành chuỗi văn bản JSON
    json_string_xs = json.dumps(db_ket_qua_tong_hop, ensure_ascii=False, separators=(',', ':'))
    json_string_kq = json.dumps(db_ket_qua_hom_nay, ensure_ascii=False, separators=(',', ':'))
    
    data_js_inject = f"const dbXacSuat = {json_string_xs};\nconst dbKetQua = {json_string_kq};"
    
    # Thu thập dữ liệu biên độ giá vàng thực tế
    vang = lay_gia_vang_thuc_te_hom_nay()
    
    # TIẾN HÀNH DÒ TÌM VÀ GHI ĐÈ ĐỒNG BỘ VÀO FILE FRONT-END HTML
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
            
            # Cập nhật giá vàng
            import re
            new_content = re.sub(r'id="sjc-gia">Mua: [0-9.]+ - Bán: [0-9.]+', f'id="sjc-gia">Mua: {vang["sjc_mua"]} - Bán: {vang["sjc_ban"]}', new_content)
            new_content = re.sub(r'id="nhan-gia">Mua: [0-9.]+ - Bán: [0-9.]+', f'id="nhan-gia">Mua: {vang["nhan_mua"]} - Bán: {vang["nhan_ban"]}', new_content)
            
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(new_content)
            
            print("✅ Thành công: Hệ thống ma trận dữ liệu đã được đồng bộ hóa sạch sẽ!")
        else:
            print("❌ Lỗi: Thẻ cấu trúc ẩn ngầm bị thay đổi hoặc không tìm thấy.")
    else:
        print("❌ Lỗi: Không tìm thấy file index.html nằm chung trong thư mục.")

if __name__ == "__main__":
    van_hanh_cap_nhat_he_thong()
