"""Import the «مدرستي» PDFs from Google Drive into this repository.

Runs inside GitHub Actions (see .github/workflows/import-from-drive.yml).
For every entry in tools/manifest.json it downloads the file by its Drive ID,
checks the size and PDF header, compresses files that exceed GitHub's 100 MB
limit, commits each grade separately and pushes. It also writes a per-page
text dump of every book to the `analysis` branch for page-numbering work.

Usage: python3 tools/import_from_drive.py [all|6|7|8|10]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "tools", "manifest.json")
REPORT = os.path.join(ROOT, "tools", "import-report.json")
TMP = "/tmp/drive-import"
ANALYSIS = "/tmp/analysis"
LIMIT = 95_000_000  # stay safely under GitHub's 100 MiB per-file limit
TRAILER = ("\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
           "Claude-Session: https://claude.ai/code/session_01E5j5hKvAXSRtoB2rfFSbiT")

URLS = [
    "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t",
    "https://drive.google.com/uc?export=download&id={id}&confirm=t",
]


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pages(path):
    out = subprocess.run(["qpdf", "--show-npages", path], capture_output=True, text=True)
    return int(out.stdout.strip()) if out.returncode in (0, 3) and out.stdout.strip() else None


def download(item, dest):
    for attempt in range(3):
        for tmpl in URLS:
            url = tmpl.format(id=item["drive_id"])
            if os.path.exists(dest):
                os.remove(dest)
            r = subprocess.run(["curl", "-sSL", "--fail", "--retry", "3", "--max-time", "1800",
                                "-o", dest, url])
            if r.returncode != 0 or not os.path.exists(dest):
                continue
            size = os.path.getsize(dest)
            with open(dest, "rb") as f:
                head = f.read(5)
            if size == item["size"] and head == b"%PDF-":
                return True
            print(f"  mismatch: got {size} bytes (want {item['size']}), header {head!r}", flush=True)
        time.sleep(10 * (attempt + 1))
    return False


def compress(src, dest):
    """Shrink an oversized PDF with Ghostscript; returns the settings used."""
    attempts = [
        ("ebook-150dpi", ["-dPDFSETTINGS=/ebook"]),
        ("120dpi", ["-dPDFSETTINGS=/ebook", "-dDownsampleColorImages=true",
                    "-dColorImageResolution=120", "-dDownsampleGrayImages=true",
                    "-dGrayImageResolution=120"]),
        ("100dpi", ["-dPDFSETTINGS=/ebook", "-dDownsampleColorImages=true",
                    "-dColorImageResolution=100", "-dDownsampleGrayImages=true",
                    "-dGrayImageResolution=100"]),
    ]
    for label, opts in attempts:
        run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
             "-dCompatibilityLevel=1.6", *opts, f"-sOutputFile={dest}", src])
        if os.path.getsize(dest) <= LIMIT:
            return label
    raise RuntimeError(f"could not compress {src} under {LIMIT} bytes")


def dump_text(pdf, rel_path):
    out = os.path.join(ANALYSIS, rel_path[:-4] + ".txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", pdf, out])


def git(*args):
    run(["git", "-C", ROOT, *args])


def push(branch="main"):
    for attempt in range(4):
        r = subprocess.run(["git", "-C", ROOT, "push", "origin", f"HEAD:{branch}"])
        if r.returncode == 0:
            return
        subprocess.run(["git", "-C", ROOT, "pull", "--rebase", "origin", branch])
        time.sleep(15)
    raise RuntimeError("push failed")


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "all"
    manifest = json.load(open(MANIFEST))["files"]
    report = json.load(open(REPORT)) if os.path.exists(REPORT) else {"files": {}}
    os.makedirs(TMP, exist_ok=True)
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")

    grades = sorted({it["grade"] for it in manifest})
    if want != "all":
        grades = [int(want)]
    failures = []
    for grade in grades:
        items = [it for it in manifest if it["grade"] == grade]
        for it in items:
            dest = os.path.join(ROOT, it["path"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            print(f"== {it['path']}  ({it['size']/1e6:.1f} MB)  {it['source_name']}", flush=True)
            raw = os.path.join(TMP, "raw.pdf")
            if not download(it, raw):
                failures.append(it["path"])
                print(f"  FAILED: {it['path']}", flush=True)
                continue
            entry = {"source_sha256": sha256(raw), "source_size": it["size"],
                     "pages": pages(raw), "compressed": None}
            if it["size"] > LIMIT:
                entry["compressed"] = compress(raw, dest)
                if pages(dest) != entry["pages"]:
                    raise RuntimeError(f"page count changed while compressing {it['path']}")
            else:
                shutil.move(raw, dest)
            entry["size"] = os.path.getsize(dest)
            entry["sha256"] = sha256(dest)
            report["files"][it["path"]] = entry
            if it["type"] == "book":
                dump_text(dest, it["path"])
            if os.path.exists(raw):
                os.remove(raw)
        report["failures"] = failures
        with open(REPORT, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        git("add", f"Grade-{grade}", "tools/import-report.json")
        r = subprocess.run(["git", "-C", ROOT, "diff", "--cached", "--quiet"])
        if r.returncode != 0:
            git("commit", "-q", "-m", f"Import Grade {grade} books and exam models from Drive" + TRAILER)
            push()

    # Per-page text of the books, on a separate branch so main stays clean.
    if os.path.isdir(ANALYSIS):
        wt = "/tmp/analysis-worktree"
        exists = subprocess.run(["git", "-C", ROOT, "ls-remote", "--exit-code", "origin", "analysis"],
                                capture_output=True).returncode == 0
        if exists:
            git("fetch", "-q", "origin", "analysis")
            git("worktree", "add", "-B", "analysis", wt, "FETCH_HEAD")
        else:
            git("worktree", "add", "--orphan", "-b", "analysis", wt)
        run(["cp", "-r", f"{ANALYSIS}/.", wt])
        run(["git", "-C", wt, "add", "-A"])
        if subprocess.run(["git", "-C", wt, "diff", "--cached", "--quiet"]).returncode != 0:
            run(["git", "-C", wt, "commit", "-q", "-m", "Book text dumps for page analysis" + TRAILER])
            run(["git", "-C", wt, "push", "origin", "HEAD:analysis"])
    if failures:
        print("FAILED FILES:", *failures, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
