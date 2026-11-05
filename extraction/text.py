"""Shared by build_text.py and update_extracted.py."""
import re, subprocess, tempfile, time

from huggingface_hub import hf_hub_download

MIN_PAGE_CHARS = 100


def download(*args, **kw):
    """Hub downloads share a request quota across the account, so wait and retry."""
    for attempt in range(8):
        try:
            return hf_hub_download(*args, **kw)
        except Exception as e:
            print(f"download failed ({attempt + 1}/8), waiting 2 min: {str(e)[:120]}", flush=True)
            time.sleep(120)
    raise RuntimeError("Hub download kept failing")


def to_text(raw, is_pdf):
    """(text, pages, pages OCRed). Pages with almost no text, except the last, are OCRed: EEOC often
    flattens page 1 to an image to redact the name."""
    if not is_pdf:
        return raw.decode("utf-8", "replace"), 0, 0
    ocr = 0
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/f.pdf"
        open(p, "wb").write(raw)
        info = subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout
        n = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        t = subprocess.run(["pdftotext", p, "-"], capture_output=True, text=True, errors="replace").stdout.split("\f")[:n]
        for i, x in enumerate(t):
            if len(x.strip()) < MIN_PAGE_CHARS and i < n - 1:
                subprocess.run(["pdftoppm", "-f", str(i + 1), "-l", str(i + 1), "-r", "200", "-png", "-singlefile", p, f"{d}/p"], check=True)
                subprocess.run(["tesseract", f"{d}/p.png", f"{d}/p"], capture_output=True, check=True)
                t[i] = open(f"{d}/p.txt").read()
                ocr += 1
    return "\f".join(t), n, ocr
