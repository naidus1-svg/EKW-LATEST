#!/usr/bin/env python3
"""golden_leak_scan.py - deterministic answer-exposure scan (canon check 1.6). For every task, extract
text from every file under environment/initial_workspace (recursive; docx, xlsx, pptx, pdf, csv, txt,
md, json, html/mhtml/.doc-as-mhtml) and from every golden file, then report the environment files whose
8-word shingles cover the largest share of the golden's shingles. DataOS found 70% on SVC-PC-8-2-0
(a "(final).doc" plan copied into /app). Writes /root/qc/_prompts/golden_leak_scan.csv and prints
tasks over --threshold (default 0.25).
"""

import argparse, csv, email, glob, html, io, os, re, sys, zipfile
from concurrent.futures import ProcessPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument(
    "--corpus-root", default="/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
)
ap.add_argument("--threshold", type=float, default=0.25)
ap.add_argument("--workers", type=int, default=8)
a = ap.parse_args()


def xml_text(z, names):
    out = []
    for n in names:
        try:
            out.append(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")))
        except Exception:
            pass
    return " ".join(out)


def extract(path):
    p = path.lower()
    try:
        if p.endswith((".docx", ".xlsx", ".pptx", ".xlsm")):
            z = zipfile.ZipFile(path)
            names = [
                n
                for n in z.namelist()
                if n.endswith(".xml")
                and (
                    "word/" in n
                    or "xl/sharedStrings" in n
                    or "xl/worksheets" in n
                    or "ppt/slides/" in n
                )
            ]
            return xml_text(z, names[:400])
        if p.endswith((".csv", ".txt", ".md", ".json", ".toml", ".tsv")):
            return open(path, encoding="utf-8", errors="ignore").read(3_000_000)
        if p.endswith((".htm", ".html", ".mht", ".mhtml", ".doc", ".eml")):
            raw = open(path, "rb").read(6_000_000)
            if (
                raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            ):  # real OLE .doc: crude text pull
                return re.sub(r"[^\x20-\x7e]+", " ", raw.decode("latin-1"))
            try:
                msg = email.message_from_bytes(raw)
                parts = []
                for part in msg.walk():
                    if part.get_content_type() in ("text/html", "text/plain"):
                        parts.append(
                            part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", "ignore"
                            )
                        )
                t = " ".join(parts) if parts else raw.decode("utf-8", "ignore")
            except Exception:
                t = raw.decode("utf-8", "ignore")
            t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
            return html.unescape(re.sub(r"<[^>]+>", " ", t))
        if p.endswith(".pdf"):
            try:
                import pdfplumber

                with pdfplumber.open(path) as pdf:
                    return " ".join((pg.extract_text() or "") for pg in pdf.pages[:60])
            except Exception:
                return ""
    except Exception:
        return ""
    return ""


def shingles(text, k=8):
    words = re.findall(r"[a-z0-9$%.,:-]+", text.lower())
    return {" ".join(words[i : i + k]) for i in range(0, max(0, len(words) - k + 1))}


def scan(td):
    tid = os.path.basename(td)
    gold = set()
    for g in glob.glob(
        os.path.join(td, "solution", "files", "**", "*"), recursive=True
    ):
        if os.path.isfile(g):
            gold |= shingles(extract(g))
    if len(gold) < 50:
        return (tid, len(gold), "", 0.0, "", 0.0, 0)
    best = []
    n = 0
    for f in glob.glob(
        os.path.join(td, "environment", "initial_workspace", "**", "*"), recursive=True
    ):
        if not os.path.isfile(f):
            continue
        n += 1
        sh = shingles(extract(f))
        if not sh:
            continue
        cov = len(gold & sh) / len(gold)
        best.append(
            (
                cov,
                os.path.relpath(
                    f, os.path.join(td, "environment", "initial_workspace")
                ),
            )
        )
    best.sort(reverse=True)
    b1 = best[0] if best else (0.0, "")
    b2 = best[1] if len(best) > 1 else (0.0, "")
    return (tid, len(gold), b1[1], round(b1[0], 3), b2[1], round(b2[0], 3), n)


if __name__ == "__main__":
    tasks = sorted(glob.glob(os.path.join(a.corpus_root, "SVC-PC-*")))
    with ProcessPoolExecutor(a.workers) as ex:
        rows = list(ex.map(scan, tasks))
    out = "/root/qc/_prompts/golden_leak_scan.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "task",
                "golden_shingles",
                "top_file",
                "top_coverage",
                "second_file",
                "second_coverage",
                "env_files",
            ]
        )
        w.writerows(rows)
    flagged = [r for r in rows if r[3] >= a.threshold]
    print(
        f"scanned {len(rows)} tasks; {len(flagged)} with an environment file covering >= {a.threshold:.0%} of the golden's 8-word shingles"
    )
    for r in sorted(flagged, key=lambda r: -r[3]):
        print(f"  {r[0]:16} {r[3]:6.1%}  {r[2][:90]}  (env files {r[6]})")
    print("csv:", out)
