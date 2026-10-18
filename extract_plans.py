"""
extract_plans.py
----------------
Reads the vector floor plans from the PDF and writes plans.json.

Every black box in the PDF is a room: its position and size (in PDF points)
and the text inside it are copied 1:1.  campus_data.py then converts points
to metres, so the 3D layout follows the PDF layout.

Usage (needs PyMuPDF:  pip install pymupdf):
    python extract_plans.py "Denah Ruangan Gedung A,B,C.pdf"
plans.json is shipped with the project, so this step is only needed if the PDF changes.
"""
import json
import re
import sys

import fitz  # PyMuPDF

# PDF page number -> (building, floor, part)   part: "main" plan or rear "wing" (Belakang)
PAGES = {
    1: ("A", 1, "main"), 2: ("A", 2, "main"), 3: ("A", 3, "main"), 4: ("A", 4, "main"),
    5: ("A", 5, "main"), 6: ("A", 6, "main"),
    7: ("B", 2, "main"), 8: ("B", 2, "wing"), 9: ("B", 3, "main"), 10: ("B", 3, "wing"),
    11: ("B", 4, "main"), 12: ("B", 4, "wing"), 13: ("B", 5, "main"), 14: ("B", 5, "wing"),
    15: ("B", 6, "main"), 16: ("B", 7, "main"), 17: ("B", 9, "main"),
    18: ("C", 8, "main"), 19: ("C", 11, "main"), 20: ("C", 12, "main"),
}

UPPER = {"OB", "TI", "FH", "PPKPT", "LKBH", "UNPAM", "IT", "BK", "LKA", "SI", "UKM", "PLC", "PLTS",
         "CBT", "IV", "MTK", "FKIP", "PGSD", "UPZ", "LKK", "VIP", "HIMA", "PINTER", "AP", "SASING",
         "SASINDO", "FIKOM", "D-3", "M.", "R.", "II", "III"}
TYPOS = {"MICORCONTROLLER": "MICROCONTROLLER", "AKUTANSI": "AKUNTANSI"}   # typos in the PDF
VCODE = re.compile(r"^V\.?\s*(\d+\s?[A-Z]?)$", re.I)


def pretty(text):
    text = re.sub(r"\bR\.(?=\S)", "R. ", text)           # R.PIMPINAN -> R. PIMPINAN
    words = []
    for w in text.split():
        w = TYPOS.get(w.upper(), w)
        words.append(w.upper() if w.upper() in UPPER else (w if w == "&" else w.capitalize()))
    return " ".join(words)


def kind_of(label, desc):
    u = label.upper()
    if u.startswith("V."):
        d = desc.upper()
        if d.startswith(("R. DOSEN", "R. SIDANG", "R. LEMBAGA", "R. SEKRETARIAT")):
            return "office"
        if d.startswith("R. JARKOM"):
            return "lab"
        return "classroom"
    if u == "LIFT":
        return "lift"
    if u == "TANGGA":
        return "stairs"
    if u == "ESKALATOR":
        return "escalator"
    if u.startswith("TOILET"):
        return "toilet"
    if u.startswith("MUSHOLLA"):
        return "prayer"
    if u.startswith("LAB "):
        return "lab"
    if u in ("GUDANG", "RUANG OB", "R. OB") or "BARANG" in u:
        return "service"
    return "office"


def parse_text(lines):
    """lines inside one box -> (label, desc, kind)"""
    if not lines:
        return "Unlabelled space", "No label in the PDF", "void"
    raw = re.sub(r"\s+", " ", " ".join(lines)).strip()
    code, rest = None, []
    for ln in lines:                       # a "V.xxx" line is the label, the rest is the description
        m = VCODE.match(ln.strip())
        if m and code is None:
            code = "V." + m.group(1).replace(" ", "")
        else:
            rest.append(ln)
    if code is None and re.match(r"^V\.?\s*\d", raw):     # e.g. "V561 (R. ...)" on one line
        m = re.match(r"^V\.?\s*(\d+[A-Z]?)\s*(.*)$", raw)
        code, rest = "V." + m.group(1), [m.group(2)]
    if code:
        desc = re.sub(r"\s+", " ", " ".join(rest)).strip().strip("()").strip()
        desc = pretty(desc) if desc else ""
        return code, desc, kind_of(code, desc)
    desc = ""
    paren = re.search(r"\(([^)]*)\)\s*$", raw)
    if paren:
        d = paren.group(1).strip()
        raw = raw[:paren.start()].strip()
        desc = f"Room {d}" if re.fullmatch(r"\d+[A-Z]?", d) else pretty(d)
    label = pretty(raw)
    return label, desc, kind_of(label, desc)


def extract(pdf_path):
    doc = fitz.open(pdf_path)
    out = []
    for pno, (b, f, part) in PAGES.items():
        page = doc[pno - 1]
        rects = []
        for d in page.get_drawings():
            if d["type"] == "s" and d["width"] and d["width"] > 3:
                r = d["rect"]
                rects.append({"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1, "lines": []})
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if not t:
                    continue
                cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
                cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
                hit = [r for r in rects if r["x0"] - 2 <= cx <= r["x1"] + 2 and r["y0"] - 2 <= cy <= r["y1"] + 2]
                if hit:     # smallest box that contains the text line
                    min(hit, key=lambda r: (r["x1"] - r["x0"]) * (r["y1"] - r["y0"]))["lines"].append(t)

        rooms = []
        for r in rects:
            prodi = [l for l in r["lines"] if l.upper().startswith("R. PRODI")]
            if len(prodi) >= 2:            # one box holding two separate prodi rooms -> split in halves
                h = (r["y1"] - r["y0"]) / len(prodi)
                for i, l in enumerate(prodi):
                    rooms.append({"x0": r["x0"], "x1": r["x1"], "y0": r["y0"] + i * h,
                                  "y1": r["y0"] + (i + 1) * h, "lines": [l]})
            else:
                rooms.append(r)

        parsed = []
        for r in rooms:
            label, desc, kind = parse_text(r["lines"])
            parsed.append({"label": label, "desc": desc, "kind": kind,
                           "x0": round(r["x0"], 2), "y0": round(r["y0"], 2),
                           "x1": round(r["x1"], 2), "y1": round(r["y1"], 2)})

        # repeated labels on one page (e.g. two "Toilet Wanita") -> West/East, North/South or numbers
        groups = {}
        for i, p in enumerate(parsed):
            groups.setdefault(p["label"], []).append(i)
        for label, idx in groups.items():
            if len(idx) < 2:
                continue
            if label.startswith("V."):
                for i in idx[1:]:
                    parsed[i]["desc"] = (parsed[i]["desc"] + " " if parsed[i]["desc"] else "") + \
                        "(second box with this code in the PDF)"
                continue
            xs = {i: (parsed[i]["x0"] + parsed[i]["x1"]) / 2 for i in idx}
            ys = {i: (parsed[i]["y0"] + parsed[i]["y1"]) / 2 for i in idx}
            horizontal = (max(xs.values()) - min(xs.values())) >= (max(ys.values()) - min(ys.values()))
            order = sorted(idx, key=lambda i: xs[i] if horizontal else ys[i])
            names = (["West", "East"] if horizontal else ["North", "South"]) if len(idx) == 2 \
                else [str(n + 1) for n in range(len(idx))]
            for n, i in zip(names, order):
                parsed[i]["label"] = f"{label} ({n})"
        out.append({"page": pno, "building": b, "floor": f, "part": part, "rooms": parsed})
    return out


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "Denah Ruangan Gedung A,B,C.pdf"
    data = extract(pdf)
    with open("plans.json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print(f"{sum(len(p['rooms']) for p in data)} boxes from {len(data)} pages -> plans.json")
