"""
Analyze banner screenshots and create structured output.
Opens screenshots for manual review and creates a framework for data extraction.
"""

from pathlib import Path
from PIL import Image
import subprocess
import sys

SCREENSHOTS_DIR = Path("game mechanics screenshots")
OUTPUT_FILE = Path("banners_data.txt")
JSON_OUTPUT = Path("banners_data.json")

def analyze_screenshot(img_path):
    """Analyze screenshot and extract basic info."""
    try:
        img = Image.open(img_path)
        width, height = img.size
        
        # Save image dimensions and basic info
        return {
            "filename": img_path.name,
            "width": width,
            "height": height,
            "format": img.format,
            "mode": img.mode,
        }
    except Exception as e:
        return {"filename": img_path.name, "error": str(e)}

def create_banner_template():
    """Create a template for banner data extraction."""
    template_content = """================================================================================
NORDHOLD BANNERS DATA EXTRACTION
================================================================================

This file will contain banner information extracted from game screenshots.

BANNER DATA STRUCTURE:

For each banner found in the screenshots, extract the following:

BANNER: [Banner Name]
TYPE: [Common/Rare/Epic/Legendary]
COST: [Cost in resources]
ICON: [Visual description]
DESCRIPTION: [What the banner does]
EFFECTS:
  - [Stat]: [Value] ([Type])
  - [Stat]: [Value] ([Type])
APPLIES_TO: [all/specific towers/conditions]
MAX_STACKS: [Number or "unlimited"]
TAGS: [keyword1, keyword2, ...]
NOTES: [Any additional information]
---

STAT TARGETS USED IN GAME:
- damage (tower damage output)
- attack_speed (rate of fire)
- range (tower reach)
- crit_chance (critical hit probability)
- crit_damage (critical hit multiplier)
- cost (building/resource cost)

VALUE TYPES:
- additive_percent: Adds percentage (e.g., +50%)
- multiplicative_percent: Multiplies by percentage (e.g., x1.25)
- flat: Adds fixed value (e.g., +100)
- multiplier: Pure multiplier (e.g., x2.0)

================================================================================
EXTRACTED BANNERS:
================================================================================

Note: Scroll through screenshots in "game mechanics screenshots" folder.
Focus on the selected banner in the center and details on the right panel.

"""
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(template_content)

def main():
    """Main function to process screenshots."""
    print("="*60)
    print("NORDHOLD BANNER DATA EXTRACTION")
    print("="*60)
    
    if not SCREENSHOTS_DIR.exists():
        print(f"ERROR: Directory not found: {SCREENSHOTS_DIR}")
        return
    
    # Get all screenshots
    screenshots = sorted(SCREENSHOTS_DIR.glob("*.jpg"))
    print(f"\nFound {len(screenshots)} screenshots")
    
    # Analyze first few screenshots
    print("\nAnalyzing screenshots...")
    sample_data = []
    for img_path in screenshots[:10]:
        info = analyze_screenshot(img_path)
        sample_data.append(info)
    
    # Print sample info
    print("\nSample screenshot info:")
    for info in sample_data[:3]:
        print(f"  {info['filename']}: {info.get('width')}x{info.get('height')}")
    
    # Create template
    create_banner_template()
    print(f"\nTemplate created: {OUTPUT_FILE}")
    
    # Save screenshot list to JSON for reference
    screenshot_list = [analyze_screenshot(img) for img in screenshots]
    with open(JSON_OUTPUT, 'w', encoding='utf-8') as f:
        import json
        json.dump(screenshot_list, f, indent=2)
    print(f"Screenshot list saved: {JSON_OUTPUT}")
    
    print("\n" + "="*60)
    print("NEXT STEPS FOR MANUAL EXTRACTION:")
    print("="*60)
    print("1. Open the screenshots folder:")
    print(f"   explorer \"{SCREENSHOTS_DIR.resolve()}\"")
    print("\n2. For each screenshot showing a banner:")
    print("   - Identify the banner name (center/cursor selection)")
    print("   - Read the details panel (right side)")
    print("   - Extract: type, cost, effects")
    print("\n3. Add data to:", OUTPUT_FILE.name)
    print("\n4. Follow the format shown in the template")
    
    # Ask if user wants to open the folder
    print("\nOpening screenshots folder...")
    subprocess.run(['explorer', str(SCREENSHOTS_DIR.resolve())], check=False)

if __name__ == "__main__":
    main()

