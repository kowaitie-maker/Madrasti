"""Build index.json from the manifest, the import report and the verified book structure.

Usage: python3 tools/build_index.py > index.json

Inputs (all in tools/):
  manifest.json        every Drive file and where it lives in this repo
  import-report.json   page counts, sizes and split pieces written by the import run
  book-structure.json  verified parts and printed-page maps for each book
"""
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = "https://raw.githubusercontent.com/kowaitie-maker/Madrasti/main/"
GRADES_AR = {6: "الصف السادس", 7: "الصف السابع", 8: "الصف الثامن", 10: "الصف العاشر"}
PART_AR = {1: "القسم الأول", 2: "القسم الثاني"}

# Books and exams are grouped under one subject key; the value is (subject key, role).
GROUP = {
    "English-StudentBook": ("English", "student_book"),
    "English-Workbook": ("English", "workbook"),
    "Arabic-Rhetoric": ("Arabic", "rhetoric_book"),
    "Arabic-Grammar": ("Arabic", "grammar_book"),
    "Arabic-Rhetoric-Grammar": ("Arabic", "rhetoric_grammar_exam"),
    "Arabic-Vocabulary": ("Arabic", "vocabulary"),
    "Islamic-Hadiths": ("Islamic", "required_hadiths"),
}
SUBJECT_AR = {
    "Arabic": "اللغة العربية", "English": "اللغة الإنجليزية", "Math": "الرياضيات",
    "Science": "العلوم", "Islamic": "التربية الإسلامية", "Social-Studies": "الاجتماعيات",
    "Biology": "الأحياء", "Physics": "الفيزياء", "Chemistry": "الكيمياء",
}
NUMBERING_AR = {
    "single": "كتاب من قسم واحد. رقم صفحة الملف = رقم الصفحة المطبوع + الإزاحة.",
    "continuous": "الترقيم المطبوع متصل بين القسمين: القسم الثاني يكمل من حيث انتهى الأول، "
                  "فرقم الصفحة المطبوع لا يتكرر في الكتاب.",
    "restarts": "الترقيم المطبوع يبدأ من جديد في القسم الثاني، فرقم الصفحة نفسه موجود في القسمين؛ "
                "حدد القسم دائماً قبل تحويل الرقم.",
}


def load(name):
    return json.load(open(os.path.join(ROOT, "tools", name), encoding="utf-8"))


def file_entry(path, rep):
    """Direct link(s) for one logical file; split files list their pieces."""
    if rep.get("split"):
        return {
            "split": True,
            "files": [{"file": p["path"], "url": RAW + p["path"], "pdf_from": p["pdf_from"],
                       "pdf_to": p["pdf_to"], "size_bytes": p["size"]} for p in rep["split"]],
        }
    return {"split": False, "file": path, "url": RAW + path, "size_bytes": rep["size"]}


def book_entry(item, rep, struct):
    entry = {
        "title_ar": item["source_name"].rsplit(".", 1)[0],
        "role": GROUP.get(item["subject"], (None, "textbook"))[1],
        **file_entry(item["path"], rep),
        "pdf_pages": rep["pages"],
        "source_drive_id": item["drive_id"],
    }
    if struct is None:
        entry["structure_verified"] = False
        return entry
    entry["structure_verified"] = True
    entry["numbering"] = struct["numbering"]
    entry["numbering_ar"] = NUMBERING_AR[struct["numbering"]]
    parts = []
    for p in struct["parts"]:
        segs = [m for m in struct["page_map"] if m["part"] == p["part"]]
        parts.append({
            "part": p["part"],
            "name_ar": PART_AR.get(p["part"], "الكتاب كاملاً") if struct["numbering"] != "single"
            else "الكتاب كاملاً",
            "pdf_from": p["pdf_from"], "pdf_to": p["pdf_to"],
            "printed_from": min(m["printed_from"] for m in segs) if segs else None,
            "printed_to": max(m["printed_to"] for m in segs) if segs else None,
        })
    entry["parts"] = parts
    entry["page_map"] = [{
        "part": m["part"], "pdf_from": m["pdf_from"], "pdf_to": m["pdf_to"],
        "printed_from": m["printed_from"], "printed_to": m["printed_to"],
        "offset": m["pdf_from"] - m["printed_from"],
    } for m in struct["page_map"]]
    if struct.get("note_ar"):
        entry["note_ar"] = struct["note_ar"]
    return entry


def main():
    manifest = load("manifest.json")["files"]
    report = load("import-report.json")["files"]
    structure = load("book-structure.json")
    grades = {}
    missing = []
    for item in manifest:
        rep = report.get(item["path"])
        if rep is None:
            missing.append({"grade": item["grade"], "source_name": item["source_name"],
                            "reason_ar": "تعذر نقل الملف"})
            continue
        subject, role = GROUP.get(item["subject"], (item["subject"], None))
        g = grades.setdefault(str(item["grade"]), {"name_ar": GRADES_AR[item["grade"]], "subjects": {}})
        s = g["subjects"].setdefault(subject, {"name_ar": SUBJECT_AR[subject], "books": [],
                                               "exams": [], "resources": []})
        if item["type"] == "book":
            s["books"].append(book_entry(item, rep, structure.get(item["path"])))
        elif item["type"] == "exam":
            s["exams"].append({
                "model": item["model_no"], "title_ar": item["source_name"].rsplit(".", 1)[0],
                **({"topic": role} if role else {}),
                **file_entry(item["path"], rep), "pdf_pages": rep["pages"],
                "source_drive_id": item["drive_id"],
            })
        else:
            s["resources"].append({
                "kind": role, "title_ar": item["source_name"].rsplit(".", 1)[0],
                **file_entry(item["path"], rep), "pdf_pages": rep["pages"],
                "source_drive_id": item["drive_id"],
            })
    extra = load("book-structure.json").get("_gaps", [])
    index = {
        "name": "Madrasti — مدرستي",
        "description_ar": "فهرس الكتب المدرسية ونماذج الاختبارات للمنهج الكويتي، مرتب حسب الصف والمادة.",
        "updated": date.today().isoformat(),
        "repository": "https://github.com/kowaitie-maker/Madrasti",
        "raw_base_url": RAW,
        "source_drive_folder": load("manifest.json")["source_folder"],
        "how_to_find_a_page_ar": [
            "اختر الصف ثم المادة ثم الكتاب من قائمة الكتب (books).",
            "حدد القسم المطلوب (part) من قائمة الأقسام (parts).",
            "ابحث في خريطة الصفحات (page_map) عن السطر الذي يحمل القسم نفسه ويقع الرقم المطبوع ضمن مداه.",
            "رقم صفحة الملف = الرقم المطبوع + الإزاحة (offset) لذلك السطر.",
            "إذا كان الكتاب مقسماً إلى عدة ملفات (split = true) فاختر الملف الذي يقع رقم صفحة الملف ضمن مداه، "
            "ورقم الصفحة داخله = رقم صفحة الملف − بداية مدى الملف + 1.",
        ],
        "grades": grades,
        "not_imported": missing,
        "not_in_source_folder_ar": extra,
    }
    print(json.dumps(index, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
