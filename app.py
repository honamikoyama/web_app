from flask import Flask, render_template, jsonify, request
import os, csv, json
from pathlib import Path
import pandas as pd
import re

app = Flask(__name__)

# ---------- 共通パス ----------
BASE = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE, "data")
BASE_P = Path(__file__).resolve().parent / "data"

POI_CSV = BASE_P / "poi_list.csv"
DESIRED_CSV = BASE_P / "desired_example.csv"
PROPOSAL_CSV = BASE_P / "optimal_solutions_example.csv"
JSON_COMPARE = BASE_P / "mock_compare.json"
USER_TYPE_CSV = BASE_P / "user_type.csv"
POI_PREF_CSV = BASE_P / "poi_preference_by_type.csv"
TRANSPORT_PREF_CSV = BASE_P / "transport_preference_by_type.csv"
PERSUASIVE_TEXT_JSON = BASE_P / "persuasive_text.json"


# ---------- ユーティリティ ----------
def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def pick(row, *keys, default=None):
    for k in keys:
        if k in row and row[k] != "":
            return row[k]
    return default

def load_poi_data():
    """
    日本語/英語ヘッダ両対応。最低限：name/緯度/経度
    """
    pois = []
    poi_path = os.path.join(DATA_DIR, "poi_list.csv")
    with open(poi_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = pick(row, "name", "施設名")
            category = pick(row, "category", "カテゴリ") or "その他"
            lat = pick(row, "latitude", "Latitude", "lat", "緯度")
            lng = pick(row, "longitude", "Longitude", "lng", "経度")
            poi_id = pick(row, "poi_id", "PoI_ID", "id")
            if not (name and lat and lng):
                continue
            pois.append({
                "id": poi_id,
                "name": name,
                "category": category,
                "lat": float(lat),
                "lng": float(lng),
            })
    return pois

def load_user_types():
    """user_type.csvを読み込み"""
    user_types = {}
    if not USER_TYPE_CSV.exists():
        return user_types
    df = pd.read_csv(USER_TYPE_CSV, encoding="utf-8-sig")
    for _, row in df.iterrows():
        user_id = str(row["User_ID"])
        user_type = str(row["User_Type"])
        user_types[f"User_{user_id}"] = user_type
    return user_types

def load_poi_preferences():
    """poi_preference_by_type.csvを読み込み"""
    prefs = {}
    if not POI_PREF_CSV.exists():
        return prefs
    df = pd.read_csv(POI_PREF_CSV, encoding="utf-8-sig")
    for col in df.columns:
        if col == "PoI_ID":
            continue
        prefs[col] = {}
        for _, row in df.iterrows():
            poi_id = int(row["PoI_ID"])
            prefs[col][poi_id] = float(row[col])
    return prefs

def load_transport_preferences():
    """transport_preference_by_type.csvを読み込み"""
    prefs = {}
    if not TRANSPORT_PREF_CSV.exists():
        return prefs
    df = pd.read_csv(TRANSPORT_PREF_CSV, encoding="utf-8-sig")
    for col in df.columns:
        if col == "transport mode":
            continue
        prefs[col] = {}
        for _, row in df.iterrows():
            mode = str(row["transport mode"]).strip()
            prefs[col][mode] = float(row[col])
    return prefs

def load_persuasive_texts():
    """persuasive_text.jsonを読み込み"""
    if not PERSUASIVE_TEXT_JSON.exists():
        return {}
    try:
        with open(PERSUASIVE_TEXT_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

# ---------- 既存：単一地図UI ----------
@app.route("/")
def index():
    pois = load_poi_data()
    return render_template("index.html", pois=pois)

@app.route("/api/plan")
def api_plan():
    user = request.args.get("user", "").strip()
    kind = "best"

    if not user.isdigit():
        return jsonify({"error": "user には数字を指定してください"}), 400
    uid = int(user)
    if uid < 1 or uid > 30:
        return jsonify({"error": "user は 1〜30 の範囲で指定してください"}), 400

    plan_path = os.path.join(DATA_DIR, "plans", str(uid), f"{kind}.json")
    if not os.path.exists(plan_path):
        return jsonify({"error": f"plan not found: {plan_path}"}), 404

    return jsonify(load_json(plan_path))

# ---------- 一覧比較（カードUI） ----------
@app.route("/ui/compare")
def ui_compare():
    return render_template("compare.html")

@app.route("/api/compare")
def api_compare():
    if not JSON_COMPARE.exists():
        return jsonify({"error": "mock_compare.json がありません"}), 404
    data = json.loads(JSON_COMPARE.read_text(encoding="utf-8"))
    return jsonify(data)

# ---------- 左右に地図で比較（希望案 vs 提案案） ----------
def _pick_col(cols, *cands):
    for c in cands:
        if c in cols: return c
    low = {str(c).strip().lower(): c for c in cols}
    for c in cands:
        k = str(c).strip().lower()
        if k in low: return low[k]
    def norm(s): return re.sub(r"[^a-z0-9]+","_",str(s).strip().lower())
    nm = {norm(c): c for c in cols}
    for c in cands:
        if norm(c) in nm: return nm[norm(c)]
    return None

def _load_poi_master_for_geo():
    df = pd.read_csv(POI_CSV, encoding="utf-8-sig")
    idc   = _pick_col(df.columns, "PoI_ID","poi_id","id")
    namec = _pick_col(df.columns, "施設名","name","名称")
    catc  = _pick_col(df.columns, "カテゴリ","category")
    latc  = _pick_col(df.columns, "Latitude","latitude","緯度")
    lngc  = _pick_col(df.columns, "Longitude","longitude","経度")
    m = {}
    for _,r in df.iterrows():
        poi_id = int(r[idc])
        m[poi_id] = {
            "name": str(r[namec]),
            "category": str(r[catc]) if catc else "その他",
            "lat": float(r[latc]), "lng": float(r[lngc])
        }
    # POI名でも検索できるように
    name_map = {}
    for poi_id, info in m.items():
        name_map[info["name"]] = poi_id
    return m, name_map

def _read_plan_csv(path: Path, poi_master: dict, name_map: dict, user_filter=None):
    """
    CSVを読み込み、指定ユーザーのプランを返す
    Slot列: start, slot1-13, return
    """
    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"Slot","POI","Transport"}.issubset(df.columns):
        return []
    
    # ユーザーフィルタ
    if user_filter and "User" in df.columns:
        df = df[df["User"] == user_filter]
    
    out = []
    for _, r in df.iterrows():
        slot = str(r["Slot"]).strip().lower()
        poi_name = str(r["POI"]).strip()
        transport = str(r["Transport"]).strip()
        
        # 座標とカテゴリの取得
        lat = lng = None
        cat = "その他"
        poi_id = None
        
        # POI名から検索
        if poi_name in name_map:
            poi_id = name_map[poi_name]
            info = poi_master[poi_id]
            lat, lng, cat = info["lat"], info["lng"], info["category"]
        
        out.append({
            "slot": slot,
            "poi_name": poi_name,
            "poi_id": poi_id,
            "category": cat,
            "mode": transport.lower(),
            "lat": lat,
            "lng": lng
        })
    
    return out


@app.route("/ui/compare-map")
def ui_compare_map():
    return render_template("compare_map.html")

@app.route("/ui/compare-map-simple")
def ui_compare_map_simple():
    return render_template("compare_map_simple.html")

@app.route("/api/compare_geo")
def api_compare_geo():
    # ユーザー指定（デフォルト: User_1）
    user = request.args.get("user", "User_1").strip()
    
    if not (POI_CSV.exists() and DESIRED_CSV.exists() and PROPOSAL_CSV.exists()):
        return jsonify({"error": "CSVが見つかりません"}), 404

    # データ読み込み
    poi_master, name_map = _load_poi_master_for_geo()
    user_types = load_user_types()
    poi_prefs = load_poi_preferences()
    transport_prefs = load_transport_preferences()
    persuasive_texts = load_persuasive_texts()
    
    # ユーザータイプ取得
    user_type = user_types.get(user, "Type A")
    
    # 説得文取得
    persuasive_text = persuasive_texts.get(user, "")
    
    # プラン読み込み
    desired  = _read_plan_csv(DESIRED_CSV, poi_master, name_map, user)
    proposal = _read_plan_csv(PROPOSAL_CSV, poi_master, name_map, user)

    # --- 混雑度・満足度計算 ---
    def _congestion_base(slot: str) -> int:
        """時間帯ベースの混雑度"""
        # slotから時間を推定
        if slot == "start" or slot == "return":
            return 0
        match = re.search(r"\d+", slot)
        if not match:
            return 25
        slot_num = int(match.group())
        # slot1=9時, slot2=10時, ..., slot13=21時
        hour = 8 + slot_num
        
        if 10 <= hour <= 15:
            return 65  # 昼ピーク
        if 8 <= hour < 10 or 15 < hour <= 18:
            return 45
        return 25

    def _icon_sat_from_10(score: float) -> int:
        """10点満点 → 5段階"""
        if score >= 8: return 5  # VerySatisfied
        if score >= 6: return 4  # Satisfied
        if score >= 4: return 3  # Neutral
        if score >= 2: return 2  # upset
        return 1  # angry

    def _icon_cong(cong: int) -> str:
        """混雑度 → アイコン"""
        if cong < 20: return "/static/img/congestion/空いている.png"
        if cong < 40: return "/static/img/congestion/やや空いている.png"
        if cong < 60: return "/static/img/congestion/普通.png"
        if cong < 80: return "/static/img/congestion/やや混雑.png"
        return "/static/img/congestion/混雑.png"

    def _icon_sat(s: int) -> str:
        """満足度1-5 → アイコン"""
        if s == 1: return "/static/img/satisfaction/angry.png"
        if s == 2: return "/static/img/satisfaction/upset.png"
        if s == 3: return "/static/img/satisfaction/Neutral.png"
        if s == 4: return "/static/img/satisfaction/Satisfied.png"
        return "/static/img/satisfaction/VerySatisfied.png"

    MODE_JP = {
        "walking": "徒歩", "walk": "徒歩",
        "rental bicycle": "レンタサイクル", "bike": "自転車",
        "city bus": "市バス", "bus": "バス",
        "taxi": "タクシー", "car": "自家用車",
        "stay": "滞在", "move": "移動"
    }
    
    # 交通手段の正規化マップ
    TRANSPORT_NORMALIZE = {
        "walking": "Walking",
        "walk": "Walking",
        "rental bicycle": "Rental Bicycle",
        "bike": "Rental Bicycle",
        "city bus": "City Bus",
        "bus": "City Bus",
        "taxi": "Taxi",
        "car": "Taxi",
    }

    def _apply_scores(plan: list, user_type: str):
        """各スロットに満足度・混雑度を付与"""
        total_satisfaction = 0
        
        for p in plan:
            slot = p["slot"]
            
            # start/returnはスキップ
            if slot in ["start", "return"]:
                p["time_display"] = "出発" if slot == "start" else "帰着"
                p["congestion"] = None
                p["satisfaction"] = None
                p["congestion_img"] = None
                p["satisfaction_img"] = None
                p["mode_jp"] = p["poi_name"]
                continue
            
            # 時刻表示用
            match = re.search(r"\d+", slot)
            if match:
                slot_num = int(match.group())
                hour = 8 + slot_num
                p["time_display"] = f"{hour:02d}\n00"
            else:
                p["time_display"] = ""
            
            # 混雑度計算
            congestion = _congestion_base(slot)
            penalty = (congestion - 50) / 100 * 3
            
            # POIスロット（偶数: slot2, 4, 6, 8, 10, 12）
            if p["poi_name"].lower() not in ["move", "移動"]:
                if p["poi_id"] and p["poi_id"] in poi_prefs.get(user_type, {}):
                    base_sat = poi_prefs[user_type][p["poi_id"]]
                    poi_sat = max(0, base_sat - penalty)
                    satisfaction_level = _icon_sat_from_10(poi_sat)
                    
                    p["congestion"] = congestion
                    p["satisfaction"] = poi_sat
                    p["satisfaction_level"] = satisfaction_level
                    p["congestion_img"] = _icon_cong(congestion)
                    p["satisfaction_img"] = _icon_sat(satisfaction_level)
                    p["mode_jp"] = p["poi_name"]
                    
                    total_satisfaction += poi_sat
                else:
                    # POI情報がない場合
                    p["congestion"] = congestion
                    p["satisfaction"] = 3.0
                    p["satisfaction_level"] = 3
                    p["congestion_img"] = _icon_cong(congestion)
                    p["satisfaction_img"] = _icon_sat(3)
                    p["mode_jp"] = p["poi_name"]
            
            # 移動スロット（奇数: slot1, 3, 5, 7, 9, 11, 13）
            else:
                transport = p["mode"].lower()
                transport_normalized = TRANSPORT_NORMALIZE.get(transport, "Walking")
                
                if transport_normalized in transport_prefs.get(user_type, {}):
                    base_sat = transport_prefs[user_type][transport_normalized]
                    transport_sat = max(0, base_sat - penalty)
                    satisfaction_level = _icon_sat_from_10(transport_sat)
                    
                    p["congestion"] = congestion
                    p["satisfaction"] = transport_sat
                    p["satisfaction_level"] = satisfaction_level
                    p["congestion_img"] = _icon_cong(congestion)
                    p["satisfaction_img"] = _icon_sat(satisfaction_level)
                    p["mode_jp"] = MODE_JP.get(transport, transport)
                    
                    total_satisfaction += transport_sat
                else:
                    # 交通手段情報がない場合
                    p["congestion"] = congestion
                    p["satisfaction"] = 5.0
                    p["satisfaction_level"] = 3
                    p["congestion_img"] = _icon_cong(congestion)
                    p["satisfaction_img"] = _icon_sat(3)
                    p["mode_jp"] = MODE_JP.get(transport, transport)
        
        return total_satisfaction

    desired_total = _apply_scores(desired, user_type)
    proposal_total = _apply_scores(proposal, user_type)

    return jsonify({
        "desired": desired,
        "proposal": proposal,
        "desired_total_satisfaction": round(desired_total, 1),
        "proposal_total_satisfaction": round(proposal_total, 1),
        "user": user,
        "user_type": user_type,
        "persuasive_text": persuasive_text
    })


def export_satisfaction_congestion_data(output_filename='data/satisfaction_congestion_example.csv'):
    """
    各ユーザーの希望案と提案案の満足度・混雑度データをCSVに出力（起動時に1回のみ）
    """
    # データ読み込み
    poi_master, name_map = _load_poi_master_for_geo()
    user_types = load_user_types()
    poi_prefs = load_poi_preferences()
    transport_prefs = load_transport_preferences()
    
    output_data = []
    
    # ユーザーごとに処理
    users = ["User_1", "User_2", "User_3"]
    
    for user in users:
        user_type = user_types.get(user, "Type A")
        
        # 希望案の処理
        desired = _read_plan_csv(DESIRED_CSV, poi_master, name_map, user)
        desired_total_sat = _calculate_route_satisfaction(desired, user_type, poi_prefs, transport_prefs)
        desired_total_cong = _calculate_route_congestion(desired)
        desired_slots = [s for s in desired if s["slot"] not in ["start", "return"]]
        desired_avg_sat = desired_total_sat / len(desired_slots) if desired_slots else 0
        desired_avg_cong = desired_total_cong / len(desired_slots) if desired_slots else 0
        
        output_data.append({
            'user_id': user,
            'route_type': 'desired',
            'total_satisfaction': round(desired_total_sat, 2),
            'total_congestion': round(desired_total_cong, 2),
            'avg_satisfaction': round(desired_avg_sat, 2),
            'avg_congestion': round(desired_avg_cong, 2),
            'num_slots': len(desired_slots)
        })
        
        # 提案案の処理
        proposal = _read_plan_csv(PROPOSAL_CSV, poi_master, name_map, user)
        proposal_total_sat = _calculate_route_satisfaction(proposal, user_type, poi_prefs, transport_prefs)
        proposal_total_cong = _calculate_route_congestion(proposal)
        proposal_slots = [s for s in proposal if s["slot"] not in ["start", "return"]]
        proposal_avg_sat = proposal_total_sat / len(proposal_slots) if proposal_slots else 0
        proposal_avg_cong = proposal_total_cong / len(proposal_slots) if proposal_slots else 0
        
        output_data.append({
            'user_id': user,
            'route_type': 'optimized',
            'total_satisfaction': round(proposal_total_sat, 2),
            'total_congestion': round(proposal_total_cong, 2),
            'avg_satisfaction': round(proposal_avg_sat, 2),
            'avg_congestion': round(proposal_avg_cong, 2),
            'num_slots': len(proposal_slots)
        })
    
    # CSVに書き込み
    output_path = Path(output_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['user_id', 'route_type', 'total_satisfaction', 'total_congestion', 
                      'avg_satisfaction', 'avg_congestion', 'num_slots']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_data)
    
    print(f"✅ Satisfaction & Congestion data exported to {output_filename}")


def _calculate_route_satisfaction(plan, user_type, poi_prefs, transport_prefs):
    """ルート全体の満足度を計算"""
    MODE_NORMALIZE = {
        "walking": "Walking", "walk": "Walking",
        "rental bicycle": "Rental Bicycle", "bike": "Rental Bicycle",
        "city bus": "City Bus", "bus": "City Bus",
        "taxi": "Taxi", "car": "Taxi",
    }
    
    def _congestion_penalty(slot):
        if slot in ["start", "return"]:
            return 0
        match = re.search(r"\d+", slot)
        if not match:
            return 0
        slot_num = int(match.group())
        hour = 8 + slot_num
        
        if 10 <= hour <= 15:
            congestion = 65
        elif 8 <= hour < 10 or 15 < hour <= 18:
            congestion = 45
        else:
            congestion = 25
        
        return (congestion - 50) / 100 * 3
    
    total_sat = 0
    for p in plan:
        if p["slot"] in ["start", "return"]:
            continue
        
        penalty = _congestion_penalty(p["slot"])
        
        # POIスロット
        if p["poi_name"].lower() not in ["move", "移動"]:
            if p["poi_id"] and p["poi_id"] in poi_prefs.get(user_type, {}):
                base_sat = poi_prefs[user_type][p["poi_id"]]
                total_sat += max(0, base_sat - penalty)
            else:
                total_sat += 3.0
        # 移動スロット
        else:
            transport = p["mode"].lower()
            transport_normalized = MODE_NORMALIZE.get(transport, "Walking")
            if transport_normalized in transport_prefs.get(user_type, {}):
                base_sat = transport_prefs[user_type][transport_normalized]
                total_sat += max(0, base_sat - penalty)
            else:
                total_sat += 5.0
    
    return total_sat


def _calculate_route_congestion(plan):
    """ルート全体の混雑度を計算"""
    def _congestion_base(slot):
        if slot in ["start", "return"]:
            return 0
        match = re.search(r"\d+", slot)
        if not match:
            return 25
        slot_num = int(match.group())
        hour = 8 + slot_num
        
        if 10 <= hour <= 15:
            return 65
        if 8 <= hour < 10 or 15 < hour <= 18:
            return 45
        return 25
    
    total_cong = 0
    for p in plan:
        if p["slot"] not in ["start", "return"]:
            total_cong += _congestion_base(p["slot"])
    
    return total_cong


if __name__ == "__main__":
    print("🚀 Generating satisfaction & congestion data...")
    export_satisfaction_congestion_data()
    
    print("🌐 Starting Flask server...")
    app.run(debug=True)