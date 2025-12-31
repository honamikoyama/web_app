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
DESIRED_CSV = BASE_P / "desired_example.csv"                # 希望案
PROPOSAL_CSV = BASE_P / "optimal_solutions_example.csv"     # 提案案
JSON_COMPARE = BASE_P / "mock_compare.json"                  # （一覧UI用：使う場合）


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
    例:
      PoI_ID, 施設名, カテゴリ, Latitude, Longitude
      poi_id, name,  category, latitude, longitude
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

# ---------- 既存：単一地図UI ----------
@app.route("/")
def index():
    pois = load_poi_data()
    return render_template("index.html", pois=pois)

@app.route("/api/plan")
def api_plan():
    user = request.args.get("user", "").strip()
    kind = "best"  # 解1固定

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
        return jsonify({"error": "mock_compare.json がありません。scripts/make_mock_compare.py を実行してください。"}), 404
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
        m[str(r[idc])] = {
            "name": str(r[namec]),
            "category": str(r[catc]) if catc else "その他",
            "lat": float(r[latc]), "lng": float(r[lngc])
        }
    return m

def _read_plan_csv(path: Path, poi_master: dict):
    # 例：Solution,User,Slot,POI,Transport / Slot=slot1 形式に対応
    df = pd.read_csv(path, encoding="utf-8-sig")
    if not {"Slot","POI","Transport"}.issubset(df.columns):
        return []
    def slot_to_h(x):
        m = re.search(r"\d+", str(x))
        return (int(m.group()) + 5) if m else None  # slot1→6:00
    out = []
    for _, r in df.iterrows():
      h = slot_to_h(r["Slot"])
      if h is None:
          continue
      name = str(r["POI"]).strip()
      lat = lng = None
      cat = "その他"
      # POI名の部分一致で座標・カテゴリを補完
      for p in poi_master.values():
          if name and name in p["name"]:
              lat, lng, cat = p["lat"], p["lng"], p["category"]
              break
      out.append({
          "slot": h,
          "time": f"{h:02d}:00",
          "poi_name": name,
          "category": cat,
          "mode": str(r["Transport"]).strip().lower(),
          "lat": lat, "lng": lng
      })
    return out


@app.route("/ui/compare-map")
def ui_compare_map():
    # 左右に2枚の地図を並べるテンプレート
    return render_template("compare_map.html")

@app.route("/api/compare_geo")
def api_compare_geo():
    # 0) mock_compare.json があれば最優先で返す（今回の擬似データ）
    if JSON_COMPARE.exists():
        data = json.loads(JSON_COMPARE.read_text(encoding="utf-8"))
        return jsonify(data)

    # 1) 無ければ CSV → 計算で作る（混雑⇄満足は反比例）
    if not (POI_CSV.exists() and DESIRED_CSV.exists() and PROPOSAL_CSV.exists()):
        return jsonify({"error": "CSVが見つかりません"}), 404

    poi_master = _load_poi_master_for_geo()
    desired  = _read_plan_csv(DESIRED_CSV,  poi_master)   # 希望案
    proposal = _read_plan_csv(PROPOSAL_CSV, poi_master)   # 提案案

    # --- スコア付与（混雑↑→満足↓、ノイズなし） ---
    def _congestion_base(hour: int) -> int:
        if 10 <= hour <= 15: return 65     # 昼ピーク
        if 8 <= hour < 10 or 15 < hour <= 18: return 45
        return 25

    def _to_satisfaction(cong: int) -> int:
        # cong:0→満足5, 100→満足1（厳密単調）
        if cong >= 70: return 1
        if cong >= 55: return 2
        if cong >= 40: return 3
        if cong >= 25: return 4
        return 5

    def _icon_cong(cong: int) -> str:
        # 5段階：0-20, 20-40, 40-60, 60-80, 80-100
        if cong < 20: return "/static/img/congestion/空いている.png"
        if cong < 40: return "/static/img/congestion/やや空いている.png"
        if cong < 60: return "/static/img/congestion/普通.png"
        if cong < 80: return "/static/img/congestion/やや混雑.png"
        return "/static/img/congestion/混雑.png"

    def _icon_sat(s: int) -> str:
        # 満足度1-5に対応
        if s == 1: return "/static/img/satisfaction/angry.png"
        if s == 2: return "/static/img/satisfaction/upset.png"
        if s == 3: return "/static/img/satisfaction/Neutral.png"
        if s == 4: return "/static/img/satisfaction/Satisfied.png"
        return "/static/img/satisfaction/VerySatisfied.png"
    # --- 英語の交通手段を日本語に変換する辞書 ---
    MODE_JP = {
        "walk": "徒歩",
        "Rental Bicycle": "レンタサイクル",
        "bike": "自転車",
        "bus": "バス",
        "city bus": "市バス",
        "loop bus": "循環バス",
        "taxi": "タクシー",
        "car": "自家用車",
        "stay": "滞在",
        "move": "移動"
    }

    def _apply_scores(plan: list, bias: int):
        # bias: 希望案=+15（悪化）/ 提案案=-15（改善）
        for p in plan:
            try:
                h = int(p.get("slot") or int(str(p.get("time")).split(":")[0]))
            except Exception:
                h = 6
            cong = max(0, min(100, _congestion_base(h) + bias))
            sat  = _to_satisfaction(cong)
            p["congestion"] = cong
            p["satisfaction"] = sat
            p["congestion_img"]   = _icon_cong(cong)
            p["satisfaction_img"] = _icon_sat(sat)
        for p in plan:
            ...
            # mode（交通手段）の日本語化
            m = str(p.get("mode", "")).strip()
            if m in MODE_JP:
                p["mode_jp"] = MODE_JP[m]
            else:
                p["mode_jp"] = m or "移動"


    _apply_scores(desired,  bias=+15)   # 希望＝悪化
    _apply_scores(proposal, bias=-15)   # 提案＝改善

    # 同時刻で差を強制（希望 >= 提案 + Δ）
    def _enforce_gap(desired, proposal, gap_peak=12, gap_off=6):
        d = {p["time"]: p for p in desired}
        q = {p["time"]: p for p in proposal}
        for t in set(d) & set(q):
            peak = 10 <= int(t[:2]) <= 15
            need = gap_peak if peak else gap_off
            if d[t]["congestion"] < q[t]["congestion"] + need:
                d[t]["congestion"] = min(100, q[t]["congestion"] + need)
                d[t]["satisfaction"] = _to_satisfaction(d[t]["congestion"])
                d[t]["congestion_img"]   = _icon_cong(d[t]["congestion"])
                d[t]["satisfaction_img"] = _icon_sat(d[t]["satisfaction"])
            if q[t]["congestion"] > d[t]["congestion"] - need:
                q[t]["congestion"] = max(0, d[t]["congestion"] - need)
                q[t]["satisfaction"] = _to_satisfaction(q[t]["congestion"])
                q[t]["congestion_img"]   = _icon_cong(q[t]["congestion"])
                q[t]["satisfaction_img"] = _icon_sat(q[t]["satisfaction"])

    _enforce_gap(desired, proposal)

    return jsonify({"desired": desired, "proposal": proposal})
# 置き換えここまで


# ---------- サーバ起動（必ず一番最後） ----------
if __name__ == "__main__":
    app.run(debug=True)