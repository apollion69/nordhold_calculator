"""
View Nordhold screenshots and extract banner data.
Opens screenshots for manual review and helps structure the data.
"""

from pathlib import Path
import subprocess
import sys

SCREENSHOTS_DIR = Path("game mechanics screenshots")
OUTPUT_FILE = Path("banners_data.txt")

def list_banners():
    """List all screenshots that appear to show banners."""
    screenshots = sorted(SCREENSHOTS_DIR.glob("*.jpg"))
    
    print(f"Found {len(screenshots)} screenshots\n")
    print("To extract banner data, you'll need to manually review each screenshot.")
    print("\nFor each screenshot showing a banner:")
    print("- Look at the selected banner in the center of the screen")
    print("- Read the details panel on the right side")
    print("- Extract: name, type, cost, effects")
    
    # Open first screenshot as example
    if screenshots:
        first_img = screenshots[0]
        print(f"\nOpening first screenshot: {first_img.name}")
        try:
            # Try to open with default system viewer
            subprocess.run(['start', str(first_img)], shell=True, check=False)
        except Exception as e:
            print(f"Could not open image: {e}")
    
    return screenshots

def create_template():
    """Create template file for banner data."""
    template = """
================================================================================
NORDHOLD BANNERS DATA
================================================================================

This file contains banner information extracted from game screenshots.

BANNER INFORMATION STRUCTURE:
- Name: Banner name as shown in game
- Type: Common, Rare, Epic, Legendary
- Cost: Banner cost in resources
- Effects: List of stat modifications
  Format: [stat_target] +[value] ([value_type])
  Example: damage +50% (additive_percent)
- Tags: Keywords that define banner behavior
- Max Stacks: How many times this banner can be used
- Exclusive: Whether multiple of this banner can be active

VALUE TYPES:
- additive_percent: Adds percentage (e.g., +50% damage)
- multiplicative_percent: Multiplies by percentage (e.g., x1.5)
- flat: Adds flat value (e.g., +100 damage)
- multiplier: Pure multiplier (e.g., x2.0)

STAT TARGETS:
- damage: Tower damage
- attack_speed: Attack speed (reload time)
- range: Tower range
- cost: Building cost
- crit_chance: Critical hit chance
- crit_damage: Critical hit damage
- etc.

================================================================================

SAMPLE ENTRY:

BANNER: Banner of Power
TYPE: Rare
COST: 150
EFFECTS:
  damage: +25% (additive_percent)
  attack_speed: +10% (multiplicative_percent)
TAGS: [damage, buff]
MAX_STACKS: 2
EXCLUSIVE: No
APPLIES_TO: all
NOTES: Increases damage for all towers
---

================================================================================
EXTRACTED BANNERS:
================================================================================

"""
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(template)
    
    print(f"Template created: {OUTPUT_FILE}")
    print("Please review screenshots and add banner data to this file.")

def main():
    print("Nordhold Banner Data Extractor")
    print("=" * 60)
    
    screenshots = list_banners()
    create_template()
    
    print(f"\nNext steps:")
    print("1. Review the screenshots (they will open automatically)")
    print(f"2. Add banner data to: {OUTPUT_FILE}")
    print("3. Follow the template format shown above")

if __name__ == "__main__":
    main()

