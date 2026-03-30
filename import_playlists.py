import os
import glob
from app.csv_importer import process_csv_content

PLAYLISTS_DIR = "playlists"

def run_bulk_import():
    csv_files = glob.glob(os.path.join(PLAYLISTS_DIR, "*.csv"))
    
    if not csv_files:
        print(f"No .csv files found in {PLAYLISTS_DIR}")
        return

    print(f"Found {len(csv_files)} playlist files.")
    
    total_imported = 0
    files_processed = 0
    
    for file_path in csv_files:
        filename = os.path.basename(file_path)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            count = process_csv_content(content, f"CSV Import: {filename}")
            if count > 0:
                print(f"[SUCCESS] {filename}: Imported {count} new songs")
                total_imported += count
            else:
                print(f"[SKIPPED] {filename}: No new songs or parsing failed")
                
            files_processed += 1
        except Exception as e:
            print(f"[ERROR] {filename}: {str(e)}")

    print(f"\nBulk Import Complete.")
    print(f"Processed: {files_processed} files")
    print(f"Total New Songs: {total_imported}")

if __name__ == "__main__":
    run_bulk_import()
