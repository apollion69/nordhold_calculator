"""
Interactive banner data extraction tool.
Opens screenshots and guides you through entering banner information.
"""

from pathlib import Path
import subprocess
import json

SCREENSHOTS_DIR = Path("game mechanics screenshots")
OUTPUT_FILE = Path("banners_data.txt")
JSON_FILE = Path("banners_data.json")

# Store extracted data
extracted_data = []

def get_screenshots():
    """Get list of banner screenshots."""
    screenshots = sorted(SCREENSHOTS_DIR.glob("*.jpg"))
    return screenshots

def open_image(img_path):
    """Open image with default viewer."""
    try:
        subprocess.run(['start', str(img_path)], shell=True, check=False)
    except Exception as e:
        print(f"Could not open image: {e}")

def extract_banner_info():
    """Interactive extraction process."""
    screenshots = get_screenshots()
    
    print("="*60)
    print("NORDHOLD BANNER DATA EXTRACTION")
    print("="*60)
    print(f"\nFound {len(screenshots)} screenshots")
    print("\nThis tool will help you extract banner data.")
    print("For each screenshot:")
    print("1. Screenshot will open")
    print("2. Enter banner information")
    print("3. Data will be saved automatically")
    
    # Process first 20 screenshots as banner candidates
    print(f"\nProcessing first 20 screenshots...")
    
    for i, img_path in enumerate(screenshots[:20], 1):
        print(f"\n{'='*60}")
        print(f"Screenshot {i}/20: {img_path.name}")
        print(f"{'='*60}")
        
        # Open the image
        open_image(img_path)
        
        print("\nExamine the screenshot now.")
        print("Look at:")
        print("  - Selected banner in center (where cursor is)")
        print("  - Details panel on the right side")
        
        # Get banner information
        banner_data = {}
        
        name = input("\nBanner name (or 'skip' to skip, 'done' to finish): ").strip()
        if name.lower() == 'done':
            break
        if name.lower() == 'skip':
            continue
            
        banner_data['name'] = name
        banner_data['filename'] = img_path.name
        
        # Get more details
        banner_type = input("Type (Common/Rare/Epic/Legendary): ").strip()
        if banner_type:
            banner_data['type'] = banner_type
        
        cost = input("Cost: ").strip()
        if cost:
            banner_data['cost'] = cost
        
        print("\nEnter effects (press Enter after each, leave empty to finish):")
        effects = []
        while True:
            effect = input("Effect (format: 'damage +50% (additive)'): ").strip()
            if not effect:
                break
            effects.append(effect)
        
        if effects:
            banner_data['effects'] = effects
        
        tags = input("Tags (comma-separated): ").strip()
        if tags:
            banner_data['tags'] = [t.strip() for t in tags.split(',')]
        
        notes = input("Notes (optional): ").strip()
        if notes:
            banner_data['notes'] = notes
        
        extracted_data.append(banner_data)
        
        # Save after each extraction
        save_to_files()
        
        print(f"\n✓ Banner '{name}' added!")
    
    print("\n" + "="*60)
    print("EXTRACTION COMPLETE")
    print("="*60)
    print(f"\nExtracted {len(extracted_data)} banners")
    print(f"Data saved to: {OUTPUT_FILE}")
    print(f"JSON data saved to: {JSON_FILE}")

def save_to_files():
    """Save extracted data to files."""
    # Save to text file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("NORDHOLD BANNERS DATA\n")
        f.write("="*80 + "\n\n")
        
        for i, banner in enumerate(extracted_data, 1):
            f.write(f"\n{'='*80}\n")
            f.write(f"BANNER #{i}\n")
            f.write(f"{'='*80}\n")
            f.write(f"Name: {banner.get('name', 'N/A')}\n")
            f.write(f"Type: {banner.get('type', 'N/A')}\n")
            f.write(f"Cost: {banner.get('cost', 'N/A')}\n")
            
            if 'effects' in banner:
                f.write("Effects:\n")
                for effect in banner['effects']:
                    f.write(f"  - {effect}\n")
            
            if 'tags' in banner:
                f.write(f"Tags: {', '.join(banner['tags'])}\n")
            
            if 'notes' in banner:
                f.write(f"Notes: {banner['notes']}\n")
            
            f.write("---\n")
    
    # Save to JSON file
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, indent=2, ensure_ascii=False)

def main():
    """Main entry point."""
    try:
        extract_banner_info()
    except KeyboardInterrupt:
        print("\n\nExtraction interrupted by user.")
        print(f"Saved {len(extracted_data)} banners before interruption.")
        save_to_files()
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()

