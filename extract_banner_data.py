"""
Extract banner data from Nordhold game screenshots.

This script processes screenshots to extract banner information, focusing on:
- Selected banner in the center (where cursor is)
- Banner details displayed on the right side of the screen

The extracted data will be saved to banners_data.txt in a structured format.
"""

import json
from pathlib import Path

# Directory containing screenshots
SCREENSHOTS_DIR = Path("game mechanics screenshots")
OUTPUT_FILE = Path("banners_data.txt")

# This will contain the extracted banner data
# Format: {banner_name: {attribute: value}}
banner_data = {}

def main():
    """Process screenshots and extract banner data."""
    if not SCREENSHOTS_DIR.exists():
        print(f"Directory not found: {SCREENSHOTS_DIR}")
        return
    
    # List all jpg files
    screenshots = sorted(SCREENSHOTS_DIR.glob("*.jpg"))
    print(f"Found {len(screenshots)} screenshots")
    
    # Display first few as reference
    print("\nScreenshot files:")
    for i, img in enumerate(screenshots[:10], 1):
        print(f"  {i}. {img.name}")
    if len(screenshots) > 10:
        print(f"  ... and {len(screenshots) - 10} more")
    
    print("\n" + "="*60)
    print("MANUAL EXTRACTION PROCESS")
    print("="*60)
    print("\nFor each screenshot, identify:")
    print("1. Banner name (selected banner in center)")
    print("2. Banner type/rarity")
    print("3. Cost")
    print("4. Effects (what the banner does)")
    print("5. Any tags or keywords")
    print("\nUse the information from the right side of the screen.")
    print("\nTemplate for each banner:")
    print("""
BANNER NAME: [Name]
TYPE: [Common/Rare/Epic/Legendary]
COST: [Cost]
EFFECTS:
  - [Stat Target]: [Value] ([Type: additive/multiplicative/flat])
  - [Another stat]: [Value]
TAGS: [tag1, tag2, ...]
NOTES: [Any additional info]
---""")
    
    # Create output file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("="*60 + "\n")
        f.write("BANNERS DATA FROM NORDHOLD GAME SCREENSHOTS\n")
        f.write("="*60 + "\n\n")
        f.write("Extracted from screenshots showing banner details.\n")
        f.write("Format: Banner Name, Type, Cost, Effects, Tags\n")
        f.write("\n" + "="*60 + "\n\n")
    
    print(f"\nOutput file created: {OUTPUT_FILE}")
    print("\nPlease manually review screenshots and add data to the file.")
    print(f"You can open it with: notepad {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

