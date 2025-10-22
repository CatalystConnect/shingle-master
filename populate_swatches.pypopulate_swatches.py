# populate_swatches.py
# Extracts square shingle swatches from assets/brochure.pdf into:
#   - swatches/<Series>/<Color>.png  (when auto-labeled)
#   - swatches_raw/pageXX_xref####.png  (if we couldn't label confidently)
#
# How to run in Codespaces (recommended):
#   1) Open the repo in Codespaces
#   2) In the terminal:  pip install -r requirements.txt
#   3) python populate_swatches.py
#
# How to run locally:
#   pip install -r requirements.txt
#   python populate_swatches.py

import os, re, math, sys
import fitz  # PyMuPDF

PDF_PATH = "assets/brochure.pdf"

# === Approved series & colors (from your confirmation) =====================
SERIES_COLORS = {
    "Timberline HDZ": [
        "Barkwood","Charcoal","Hickory","Hunter Green","Mission Brown","Pewter Gray",
        "Shakewood","Slate","Weathered Wood","Appalachian Sky","Nantucket Morning",
        "Golden Harvest","Cedar Falls","Biscayne Blue","Birchwood","Copper Canyon",
        "Driftwood","Fox Hollow Gray","Golden Amber","Oyster Gray","Patriot Red",
        "Sunset Brick","Williamsburg Slate"
    ],
    "Timberline UHDZ": ["Barkwood","Charcoal","Pewter Gray","Shakewood","Slate","Weathered Wood"],
    "Timberline NS":   ["Weathered Wood","Barkwood","Charcoal","Pewter Gray","Shakewood","Slate","Hickory"],
    "Grand Sequoia":   ["Charcoal","Autumn Brown","Weathered Wood","Cedar Mesa Brown"],
    "Camelot II":      ["Weathered Timber","Antique Slate","Charcoal","Barkwood","Royal Slate"],
    "Woodland":        ["Cedarwood Abbey","Castlewood Gray"],
    "Slateline":       ["Royal Slate","Antique Slate","English Gray","Weathered Slate"],
    "Timberline AS II":["Charcoal","Dusky Gray","Weathered Wood","Hickory","Adobe Sunset","Pewter Gray","Barkwood","Shakewood","Slate"],
    "Grand Sequoia AS":["Charcoal","Dusky Gray","Weathered Wood"],
    "Timberline HDZ RS":["Sagewood","Stone Gray","Hickory","Aged Chestnut","Coastal Slate","Sandalwood","Charcoal"],
    "Grand Sequoia RS":["Sandalwood","Ocean Gray","Charcoal","Forest Brown","Sagewood"],
    "Royal Sovereign": ["Charcoal","Weathered Gray"],
}
SERIES_NAMES = list(SERIES_COLORS.keys())
ALL_COLOR_LOWER = {c.lower() for colors in SERIES_COLORS.values() for c in colors}

def norm(s): 
    return re.sub(r"\s+", " ", s or "").strip().lower()

def detect_series(text):
    t = norm(text)
    # Prefer longer names first to avoid substring collisions
    for series in sorted(SERIES_NAMES, key=len, reverse=True):
        if norm(series) in t:
            return series
    return None

def is_square_swatch(pix):
    # Heuristic: square-ish and not tiny
    w, h = pix.width, pix.height
    if w < 180 or h < 180:
        return False
    ar = w / float(h)
    return 0.85 <= ar <= 1.18

def nearest_color_label(words, rect, allowed_colors=None):
    """Pick the closest word that is an allowed color label."""
    if not words:
        return None
    cx, cy = rect.x0 + rect.width/2, rect.y0 + rect.height/2
    best_text = None
    best_d = 1e12

    # Build lookup for allowed colors
    allowed = set(map(norm, allowed_colors)) if allowed_colors else ALL_COLOR_LOWER

    for (x0,y0,x1,y1,txt, *_rest) in words:
        raw = txt.strip()
        nm = norm(raw)
        if nm in allowed:
            wx, wy = (x0 + x1)/2, (y0 + y1)/2
            # Require reasonable local proximity to avoid grabbing headers
            if abs(wy - cy) < 260 and abs(wx - cx) < 260:
                d = (wx - cx)**2 + (wy - cy)**2
                if d < best_d:
                    best_d = d
                    best_text = raw
    return best_text

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p

def main():
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: {PDF_PATH} not found. Upload your brochure PDF to assets/brochure.pdf and re-run.")
        sys.exit(1)

    doc = fitz.open(PDF_PATH)
    out_root = ensure_dir("swatches")
    raw_root = ensure_dir("swatches_raw")

    saved_swatches = 0
    saved_raw = 0

    # Iterate full xref table to catch images not referenced by page content streams
    n = doc.xref_length() if hasattr(doc, "xref_length") else doc._get_xref_length()
    # Build page words and page text cache to label by proximity & series
    page_words_cache = {}
    page_text_cache = {}

    for pidx in range(len(doc)):
        page = doc[pidx]
        page_words_cache[pidx] = page.get_text("words")  # list of tuples
        page_text_cache[pidx] = page.get_text()

    # Helper to save pixmap
    def save_pixmap(pix, out_path):
        if pix.n >= 4:
            try:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            except Exception:
                pix = fitz.Pixmap(pix, 0)
        pix.save(out_path)

    for xref in range(1, n):
        try:
            subtype = doc.xref_get_key(xref, "Subtype")[1] or ""
        except Exception:
            continue
        if "/Image" not in subtype:
            continue

        # Find rectangles where this image appears on pages
        appeared = False
        for pidx in range(len(doc)):
            rects = doc[pidx].get_image_rects(xref)
            if not rects:
                continue
            appeared = True
            page = doc[pidx]
            series_hint = detect_series(page_text_cache[pidx])
            words = page_words_cache[pidx]

            # Load the pixmap once
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception:
                continue

            for rect in rects:
                # Accept only square-ish, good-sized images (likely the swatches)
                if not is_square_swatch(pix):
                    continue

                # Choose allowed color list by series, if we have a series hint
                allowed_colors = SERIES_COLORS.get(series_hint) if series_hint else None
                color_guess = nearest_color_label(words, rect, allowed_colors)

                if series_hint and color_guess:
                    out_dir = ensure_dir(os.path.join(out_root, series_hint))
                    out_path = os.path.join(out_dir, f"{color_guess}.png")
                else:
                    out_dir = raw_root
                    out_path = os.path.join(out_dir, f"page{pidx:02d}_xref{xref}_w{pix.width}_h{pix.height}.png")

                save_pixmap(pix, out_path)

                if series_hint and color_guess:
                    saved_swatches += 1
                else:
                    saved_raw += 1

        # If image never appeared (rare), skip
        if not appeared:
            continue

    print(f"Done. Matched swatches: {saved_swatches}, Unlabeled (swatches_raw): {saved_raw}")
    print("If any color is mis-labeled, rename the file in swatches/<Series>/ to the exact color text used in index.html.")

if __name__ == "__main__":
    main()

