"""Build tools/manifest.json from a Google Drive listing of the «مدرستي» folder.

Usage: python3 tools/build_manifest.py <drive_listing.json> > tools/manifest.json
The listing is the JSON returned by a Drive search over the grade sub-folders.
"""
import json
import re
import sys

FOLDERS = {
    # parent folder id prefix -> (grade, kind)
    "1YrOejfu": (6, "Books"), "1XigLimy": (6, "Exams"),
    "16tUi_Go": (7, "Books"), "1P6laF6_": (7, "Exams"),
    "1ZZhdXhG": (8, "Books"), "13CsyalI": (8, "Exams"),
    "1h7KisZx": (10, "Books"), "1-CH2dzh": (10, "Exams"),
}

# (keyword list, subject code, Arabic subject name, type override)
RULES = [
    (["Work Book"], "English-Workbook", "اللغة الإنجليزية — كتاب التمارين", None),
    (["Student"], "English-StudentBook", "اللغة الإنجليزية — كتاب الطالب", None),
    (["انجليزي"], "English", "اللغة الإنجليزية", None),
    (["الثروه اللغوي", "الثروة اللغوي"], "Arabic-Vocabulary", "اللغة العربية — الثروة اللغوية", "resource"),
    (["الأحاديث المقررة"], "Islamic-Hadiths", "التربية الإسلامية — الأحاديث المقررة", "resource"),
    (["فنون البلاغة و قواعد"], "Arabic-Rhetoric-Grammar", "فنون البلاغة وقواعد النحو والصرف", None),
    (["فنون البلاغة"], "Arabic-Rhetoric", "فنون البلاغة", None),
    (["قواعد النحو"], "Arabic-Grammar", "قواعد النحو والصرف", None),
    (["رياضيات", "الرياضيات"], "Math", "الرياضيات", None),
    (["علوم", "العلوم"], "Science", "العلوم", None),
    (["اجتماعيات", "دولة الكويت", "الكويت والعالم"], "Social-Studies", "الاجتماعيات", None),
    (["اسلامي", "الإسلامية", "الاسلامية"], "Islamic", "التربية الإسلامية", None),
    (["أحياء", "احياء"], "Biology", "الأحياء", None),
    (["الفيزيا"], "Physics", "الفيزياء", None),
    (["الكيمياء"], "Chemistry", "الكيمياء", None),
    (["لغتي العربية", "اللغة العربية", "عربي"], "Arabic", "اللغة العربية", None),
]

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def classify(title):
    for keys, code, ar, override in RULES:
        if any(k in title for k in keys):
            return code, ar, override
    raise SystemExit(f"Unclassified file: {title}")


def suffix_number(title):
    stem = title.rsplit(".", 1)[0].translate(ARABIC_DIGITS).strip()
    m = re.search(r"(\d+)$", stem)
    return int(m.group(1)) if m else 0


def main():
    files = json.load(open(sys.argv[1]))["files"]
    items, exam_groups = [], {}
    for f in files:
        grade, kind = FOLDERS[f["parentId"][:8]]
        code, ar, override = classify(f["title"])
        item = {
            "grade": grade,
            "folder": kind,
            "type": override or ("book" if kind == "Books" else "exam"),
            "subject": code,
            "subject_ar": ar,
            "drive_id": f["id"],
            "source_name": f["title"],
            "size": int(f["fileSize"]),
        }
        if item["type"] == "exam":
            exam_groups.setdefault((grade, code), []).append(item)
        else:
            item["path"] = f"Grade-{grade}/{kind}/{code}.pdf"
        items.append(item)
    for (grade, code), group in exam_groups.items():
        group.sort(key=lambda it: (suffix_number(it["source_name"]), it["source_name"]))
        for n, it in enumerate(group, 1):
            it["path"] = f"Grade-{grade}/Exams/{code}-Exam-{n}.pdf"
            it["model_no"] = n
    items.sort(key=lambda it: (it["grade"], it["folder"], it["path"]))
    paths = [it["path"] for it in items]
    assert len(paths) == len(set(paths)), "duplicate destination paths"
    json.dump({"source_folder": "https://drive.google.com/drive/folders/13P7yaPwDcBwPPedxMcpd-Ui2UxGd0tpX",
               "files": items}, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
