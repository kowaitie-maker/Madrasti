"""Detect printed page numbers and part (القسم) boundaries in book text dumps.

Input: a `pdftotext -layout` dump (pages separated by form feeds).
Output (JSON on stdout): for every PDF page, the printed page number found in
its header/footer lines (if any), whether the page looks like a part cover,
and the consistent offset segments (pdf_page - printed_page).

Usage: python3 tools/analyze_pages.py <dump.txt> [<dump.txt> ...]
"""
import json
import re
import sys
import unicodedata

DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PART_MARKERS = {
    1: ["القسم الأول", "القسم الاول", "الجزء الأول", "الجزء الاول", "الفصل الدراسي الأول",
        "الفصل الدراسي الاول"],
    2: ["القسم الثاني", "الجزء الثاني", "الفصل الدراسي الثاني"],
}


def norm(s):
    s = unicodedata.normalize("NFKC", s).translate(DIGITS)
    s = re.sub("[‎‏‪-‮⁦-⁩]", "", s)  # invisible bidi marks
    return re.sub("[ً-ْـ]", "", s)  # harakat and tatweel


def has_marker(text, words):
    flat = re.sub(r"\s+", " ", text)
    for w in words:
        if w in flat or w[::-1] in flat:
            return True
        # tolerate letters split by spaces in extracted Arabic
        if w.replace(" ", "") in flat.replace(" ", ""):
            return True
    return False


def page_number(lines):
    """Return candidate printed page numbers from the edge lines of a page."""
    edge = [l for l in lines if l.strip()]
    edge = edge[:3] + edge[-3:]
    found = []
    for l in edge:
        stripped = l.strip()
        # lone number on the line, or number at either end of the line
        for m in re.finditer(r"(?:^|\s{3,})(\d{1,3})(?:\s{3,}|$)", stripped):
            found.append(int(m.group(1)))
    return list(dict.fromkeys(found))  # unique, keep order


def segments(per_page):
    """Group pages into runs that share the same offset (pdf - printed)."""
    points = [(p["pdf"], p["printed"]) for p in per_page if p["printed"] is not None]
    segs = []
    for pdf, printed in points:
        off = pdf - printed
        if segs and segs[-1]["offset"] == off:
            segs[-1]["pdf_to"] = pdf
            segs[-1]["printed_to"] = printed
            segs[-1]["hits"] += 1
        else:
            segs.append({"offset": off, "pdf_from": pdf, "pdf_to": pdf,
                         "printed_from": printed, "printed_to": printed, "hits": 1})
    segs = [s for s in segs if s["hits"] >= 3]
    merged = []  # rejoin runs that a stray misread split apart
    for s in segs:
        if merged and merged[-1]["offset"] == s["offset"]:
            merged[-1].update(pdf_to=s["pdf_to"], printed_to=s["printed_to"],
                              hits=merged[-1]["hits"] + s["hits"])
        else:
            merged.append(s)
    return merged


def analyze(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    pages = raw.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    out, prev = [], None
    for i, text in enumerate(pages, 1):
        t = norm(text)
        lines = t.splitlines()
        cands = page_number(lines)
        printed = None
        # prefer the candidate that continues the previous page's number
        if prev is not None and (prev + 1) in cands:
            printed = prev + 1
        elif cands:
            printed = cands[-1] if len(cands) == 1 else None
            if printed is None:
                # several numbers: keep one that keeps the offset of the last page
                last = next((o for o in reversed(out) if o["printed"] is not None), None)
                if last:
                    want = i - (last["pdf"] - last["printed"])
                    printed = want if want in cands else None
        if printed is not None:
            prev = printed
        part = None
        head = "\n".join(lines[:25])
        for k, words in PART_MARKERS.items():
            if has_marker(head, words):
                part = k
        out.append({"pdf": i, "printed": printed, "candidates": cands[:6],
                    "part_marker": part, "chars": len(t.strip())})
    return {"file": path, "pdf_pages": len(pages), "segments": segments(out), "pages": out}


if __name__ == "__main__":
    print(json.dumps([analyze(p) for p in sys.argv[1:]], ensure_ascii=False, indent=1))
