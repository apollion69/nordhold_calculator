"""
Extract banner information from Nordhold screenshots using OCR.
Attempts to read text from screenshots to identify banner names and effects.
"""

from pathlib import Path
import sys

try:
    from PIL import Image
    import pytesseract
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Install with: pip install Pillow pytesseract")
    print("Also install Tesseract OCR from: https://github.com/tesseract-ocr/tesseract")
    sys.exit(1)

SCREENSHOTS_DIR = Path("game mechanics screenshots")
OUTPUT_FILE = Path("banners_data_ocr.txt")

def extract_text_from_image(img_path):
    """Extract text from image using OCR."""
    try:
        image = Image.open(img_path)
        # Try to extract text from the image
        # Focus on right side where banner details are shown
        width, height = image.size
        
        # Crop right half of image (where banner details are displayed)
        right_half = image.crop((width // 2, 0, width, height))
        
        # Extract text
        text = pytesseract.image_to_string(right_half, lang='eng+rus')
        return text
    except Exception as e:
        return f"ERROR: {str(e)}"

def process_screenshots():
    """Process all screenshots and extract banner data."""
    screenshots = sorted(SCREENSHOTS_DIR.glob("*.jpg"))
    
    print(f"Processing {len(screenshots)} screenshots...")
    print("\nNOTE: This script attempts to extract text using OCR.")
    print("Results may not be perfect - manual review is recommended.\n")
    
    results = []
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("BANNER DATA EXTRACTED FROM SCREENSHOTS (OCR Results)\n")
        f.write("=" * 80 + "\n\n")
        
        for i, img_path in enumerate(screenshots[:20], 1):  # Process first 20
            print(f"Processing {i}/20: {img_path.name}...", end=' ')
            
            text = extract_text_from_image(img_path)
            
            f.write(f"\n{'='*80}\n")
            f.write(f"SCREENSHOT: {img_path.name}\n")
            f.write(f"{'='*80}\n")
            f.write(text)
            f.write(f"\n{'='*80}\n\n")
            
            print("OK")
            
            if text.strip():
                results.append((img_path.name, text))
    
    print(f"\nExtraction complete!")
    print(f"Results saved to: {OUTPUT_FILE}")
    print(f"Found {len(results)} screenshots with text")
    
    if results:
        print("\nSample extracted text:")
        for name, text in results[:3]:
            print(f"\n{name}:")
            print(text[:200] + "..." if len(text) > 200 else text)

if __name__ == "__main__":
    process_screenshots()

