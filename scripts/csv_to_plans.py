# web_app/scripts/csv_to_plans.py
# CSV: columns = Solution, User, Slot, POI, Transport
#   - Solution: "Solution_1" 等 → 解1のみ採用
#   - User: "User_12" 等 → 数字 12 を抽出（1〜20 を想定）
#   - Slot: "slot7" 等 → 数字 7 に変換（6:00 起点で 1..15）
#   - POI: 滞在時は施設名、移動行は "move"
#   - Transport: "stay", "Walking", "Rental Bicycle" など
#
# 実行:
#   cd web_app
#   python scripts/csv_to_plans.py --csv ./data/optimal_solutions.csv --out ./data/plans --solution 1

import argparse, csv, json, re
from pathlib import Path
from collections import defaultdict

def user_to_num(u: str):
    m = re.search(r"\d+", str(u))
    return int(m.group(0)) if m else None

def slot_to_num(s: str):
    m = re.search(r"\d+", str(s))
    return int(m.group(0)) if m else None

def norm_mode(transport: str, poi: str):
    t = str(transport).strip().lower()
    if t == "stay" or str(poi).strip().lower() != "move":
        return "stay"
    if t in ("walking","walk"):
        return "walk"
    if t in ("rental bicycle","bicycle","bike","cycling"):
        return "bicycle"
    if t in ("bus","transit","public","public_transit"):
        return "bus"
    if t in ("car","drive","driving"):
        return "car"
    return t or "walk"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/optimal_solutions.csv")
    ap.add_argument("--out", default="data/plans")
    ap.add_argument("--solution", default="1")
    args = ap.parse_args()

    src = Path(args.csv)
    out_root = Path(args.out)
    sol_pick = f"solution_{str(args.solution).lstrip('0')}".lower()

    if not src.exists():
        raise FileNotFoundError(f"CSV not found: {src}")
    out_root.mkdir(parents=True, exist_ok=True)

    # read
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        req = ["Solution","User","Slot","POI","Transport"]
        for r in req:
            if r not in rd.fieldnames:
                raise ValueError(f"列が見つかりません: {r} / fields={rd.fieldnames}")

        plans = defaultdict(list)
        n_rows = 0
        n_used = 0

        for row in rd:
            n_rows += 1
            if str(row["Solution"]).strip().lower() != sol_pick:
                continue
            uid = user_to_num(row["User"])
            slot = slot_to_num(row["Slot"])
            if uid is None or slot is None:
                continue
            mode = norm_mode(row["Transport"], row["POI"])
            item = {"slot": slot, "mode": mode}
            if mode == "stay":
                name = str(row["POI"]).strip()
                item["poi_name"] = "（未指定）" if name == "" or name.lower() == "move" else name
            plans[uid].append(item)
            n_used += 1

    # write
    for uid, items in plans.items():
        items_sorted = sorted(items, key=lambda x: x["slot"])
        out_dir = out_root / str(uid)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "best.json").write_text(
            json.dumps({"items": items_sorted}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    print(f"[OK] 読込 {n_rows} / 採用（解{args.solution}）{n_used} → {len(plans)} ユーザー出力")
    print(f"出力先: {out_root.resolve()} / <user>/best.json")

if __name__ == "__main__":
    main()
