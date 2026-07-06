from pathlib import Path

from forecaster.agents.technical_analysis.image_extractor import extract_images_from_pdf


def test_extract_images_from_bulkowski_pdf(tmp_path):
    pdf_path = (
        Path(__file__).resolve().parents[1]
        / "forecaster"
        / "agents"
        / "technical_analysis"
        / "Bulkowski_Encyclopedia_of_Chart_Patterns.pdf"
    )

    output_dir = tmp_path / "bulkowski_images"
    extracted_files = extract_images_from_pdf(pdf_path, output_dir)

    assert extracted_files, "expected at least one image to be extracted"
    assert any(output_dir.glob("*.png")), "no PNG files were written"
