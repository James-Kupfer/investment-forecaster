import fitz
from pathlib import Path

def extract_images_from_pdf(pdf_path, output_dir):
    doc = fitz.open(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for page_num, page in enumerate(doc):
        images = page.get_images()
        for img_index, img in enumerate(images):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            
            if pix.n - pix.alpha < 4:  # GRAY or RGB
                filename = output_dir / f"page_{page_num}_img_{img_index}.png"
                pix.save(filename)
            else:  # CMYK
                rgb = fitz.Pixmap(fitz.csRGB, pix)
                filename = output_dir / f"page_{page_num}_img_{img_index}.png"
                rgb.save(filename)
            pix = None

extract_images_from_pdf("input.pdf", "output_images")