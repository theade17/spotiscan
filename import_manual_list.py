import re
from sqlmodel import Session, select
from app.database import engine, Song, Source

KEY_YEAR_SWITCH = 1996

def normalize(text):
    return text.strip()

def import_manual_list(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()

    current_year = None
    inserted_count = 0
    skipped_count = 0
    
    # Create or get Source
    source_name = "Manual Import (User Request)"
    with Session(engine) as session:
        source = session.exec(select(Source).where(Source.name == source_name)).first()
        if not source:
            source = Source(name=source_name, type="manual")
            session.add(source)
            session.commit()
            session.refresh(source)
        source_id = source.id

    # Regex for "NUMBER. TEXT - TEXT"
    # Handles "." after number, and "-" or "–" as separator
    # Capture group 1: Whole text after number
    line_pattern = re.compile(r'^\d+\.\s+(.+)$')

    with Session(engine) as session:
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if year
            if re.match(r'^\d{4}$', line):
                current_year = int(line)
                print(f"Processing Year: {current_year}")
                continue

            # Parse song line
            match = line_pattern.match(line)
            if match and current_year:
                content = match.group(1)
                
                # Split by - or –
                # We need to be careful about multiple dashes, usually the first one or the one with spaces around it is the separator
                # The user data has " - " or " – " (en dash) or sometimes just "-"
                
                parts = re.split(r'\s+[-–]\s+', content, maxsplit=1)
                
                if len(parts) < 2:
                    # Fallback for tight formatting or other separators?
                    # Try splitting by just "-" if space split failed
                    if '-' in content:
                        parts = content.split('-', 1)
                    elif '–' in content:
                         parts = content.split('–', 1)
                
                if len(parts) == 2:
                    part1 = normalize(parts[0])
                    part2 = normalize(parts[1])
                    
                    if current_year < KEY_YEAR_SWITCH:
                        # 1990-1995: Title - Artist
                        title = part1
                        artist = part2
                    else:
                        # 1996-2000: Artist - Title
                        artist = part1
                        title = part2
                    
                    # Deduplication
                    # Check if exact title/artist exists
                    existing = session.exec(select(Song).where(
                        (Song.title == title) & (Song.artist == artist)
                    )).first()
                    
                    if not existing:
                        song = Song(
                            title=title,
                            artist=artist,
                            year=str(current_year),
                            source_id=source_id
                        )
                        session.add(song)
                        inserted_count += 1
                        print(f"Inserted: {title} - {artist} ({current_year})")
                    else:
                        skipped_count += 1
                        # print(f"Skipped (Duplicate): {title} - {artist}")
                else:
                    print(f"Failed to parse line: {line}")
        
        session.commit()
    
    print(f"\nImport Finished.")
    print(f"Inserted: {inserted_count}")
    print(f"Skipped: {skipped_count}")

if __name__ == "__main__":
    import_manual_list("manual_songs.txt")
