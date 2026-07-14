import importlib.util
from pathlib import Path

# image_extractor.py lives in "Technical Analysis/" (space in the folder name),
# so it isn't a normal importable package — load it directly by file path.
_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "Technical Analysis" / "image_extractor.py"
)
_spec = importlib.util.spec_from_file_location("image_extractor", _MODULE_PATH)
_image_extractor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_image_extractor)
extract_images_from_pdf = _image_extractor.extract_images_from_pdf


def test_extract_images_from_bulkowski_pdf(tmp_path):
    pdf_path = (
        Path(__file__).resolve().parents[1]
        / "Technical Analysis"
        / "Bulkowski_Encyclopedia_of_Chart_Patterns.pdf"
    )

    output_dir = tmp_path / "bulkowski_images"
    extracted_files = extract_images_from_pdf(pdf_path, output_dir)

    assert extracted_files, "expected at least one image to be extracted"
    assert any(output_dir.glob("*.png")), "no PNG files were written"
