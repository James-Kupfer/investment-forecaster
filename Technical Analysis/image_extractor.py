# Run with powershell:
# & "C:\Users\James Kupfer\Claude\investment-forecaster\.venv\Scripts\python.exe" "C:\Users\James Kupfer\Claude\investment-forecaster\Technical Analysis\image_extractor.py" "C:\Users\James Kupfer\Claude\investment-forecaster\Technical Analysis\Bulkowski_Encyclopedia_of_Chart_Patterns.pdf" "C:\Users\James Kupfer\Claude\investment-forecaster\Technical Analysis\images"

import argparse
from pathlib import Path

try:
    import fitz
except ModuleNotFoundError as exc:
    if exc.name == "frontend":
        import pymupdf as fitz
    else:
        raise


def extract_images_from_pdf(pdf_path, output_dir):
    """Extract embedded images from a PDF into a target directory.

    Returns a list of generated image paths.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    extracted_files = []

    for page_num, page in enumerate(doc):
        for img_index, img in enumerate(page.get_images()):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)

            try:
                if pix.n - pix.alpha < 4:
                    image_path = output_dir / f"page_{page_num}_img_{img_index}.png"
                    pix.save(image_path)
                else:
                    rgb_pix = fitz.Pixmap(fitz.csRGB, pix)
                    image_path = output_dir / f"page_{page_num}_img_{img_index}.png"
                    rgb_pix.save(image_path)
                    rgb_pix = None
            finally:
                pix = None

            extracted_files.append(image_path)

    return extracted_files


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract images from a PDF")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("output_dir", help="Directory to save the extracted images")
    args = parser.parse_args(argv)

    extracted_files = extract_images_from_pdf(args.pdf_path, args.output_dir)
    print(f"Extracted {len(extracted_files)} image(s) to {args.output_dir}")
    return extracted_files


if __name__ == "__main__":
    main()
