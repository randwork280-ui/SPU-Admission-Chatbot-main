import json
import logging
from pathlib import Path
from docling.document_converter import DocumentConverter

def convert_pdf(source_path, output_dir):
    # 1. Setup logging to see internal progress (optional but helpful)
    logging.basicConfig(level=logging.INFO)
    
    # 2. Initialize the converter
    # This automatically handles model loading the first time you run it
    converter = DocumentConverter()
    
    # 3. Convert the document
    # source_path can be a local file path or a URL
    print(f"Converting: {source_path}...")
    result = converter.convert(source_path)
    
    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 4. Export to Markdown
    # Markdown is great for readability and feeding into LLMs
    md_output = result.document.export_to_markdown()
    md_file = output_path / "output.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_output)
    print(f"✅ Markdown saved to: {md_file}")
    
    # 5. Export to JSON
    # JSON preserves deep structure (coordinates, table cells, page numbers)
    json_output = result.document.export_to_dict()
    json_file = output_path / "output.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON saved to: {json_file}")

if __name__ == "__main__":
    # OPTIONS:
    # 1. Use a URL (e.g., Docling's own paper on Arxiv)
    SOURCE_PDF = "https://arxiv.org/pdf/2408.09869" 
    
    # 2. OR use a local file (uncomment below and change path)
    # SOURCE_PDF = "path/to/your/document.pdf"
    
    OUTPUT_FOLDER = "docling_results"
    
    try:
        convert_pdf(SOURCE_PDF, OUTPUT_FOLDER)
        print("\n🎉 Conversion complete!")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
