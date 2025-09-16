import os
import fitz  # PyMuPDF
from PIL import Image  # <-- import Pillow

OUTPUT_FOLDER = "pdf_pngs"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

for filename in os.listdir("."):
    if filename.lower().endswith(".pdf"):
        pdf_path = os.path.abspath(filename)
        base_name = os.path.splitext(filename)[0]

        doc = fitz.open(pdf_path)

        images = []
        widths, heights = [], []
        for page in doc:
            pix = page.get_pixmap(dpi=150)  # render page
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
            widths.append(pix.width)
            heights.append(pix.height)

        if len(images) == 1:
            out_path = os.path.join(OUTPUT_FOLDER, f"{base_name}.png")
            images[0].save(out_path, "PNG")
        else:
            # Merge pages vertically into one PNG
            total_height = sum(heights)
            max_width = max(widths)
            merged = Image.new("RGB", (max_width, total_height), "white")

            y_offset = 0
            for img in images:
                merged.paste(img, (0, y_offset))
                y_offset += img.height

            out_path = os.path.join(OUTPUT_FOLDER, f"{base_name}.png")
            merged.save(out_path, "PNG")

        print(f"[✔] Converted {filename} → {out_path}")
