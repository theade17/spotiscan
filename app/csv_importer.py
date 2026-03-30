import csv
import io
from fastapi import UploadFile
from sqlmodel import Session, select
from .database import engine, Song, Source

import zipfile

async def process_csv(file: UploadFile, user_id: int = None):
    content = await file.read()
    filename = file.filename.lower()
    
    if filename.endswith('.zip'):
        # Handle ZIP file
        import io
        total_inserted = 0
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for zip_info in z.infolist():
                if zip_info.filename.lower().endswith('.csv'):
                    with z.open(zip_info) as csv_file:
                        csv_content = csv_file.read().decode('utf-8', errors='replace')
                        total_inserted += process_csv_content(csv_content, f"ZIP: {zip_info.filename}", user_id=user_id)
        return total_inserted
    else:
        # Handle single CSV
        decoded = content.decode('utf-8', errors='replace')
        return process_csv_content(decoded, f"CSV Import: {file.filename}", user_id=user_id)

def process_csv_content(content_text: str, source_name: str, user_id: int = None):
    reader = csv.DictReader(io.StringIO(content_text))
    
    # Check headers
    # Exportify uses: "Track URI", "Track Name", "Artist URI", "Artist Name", "Album URI", "Album Name", ...
    # We need "Track Name" and "Artist Name"
    
    # Normalize headers
    reader.fieldnames = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
    print(f"Processing {source_name}. Headers: {reader.fieldnames}")
    
    # Identify columns
    # We look for 'Track Name' or 'Name' or 'Title'
    title_col = next((h for h in reader.fieldnames if h.lower() in ['track name', 'track', 'name', 'title', 'song']), None)
    artist_col = next((h for h in reader.fieldnames if h.lower() in ['artist name(s)', 'artist name', 'artist', 'performer', 'band']), None)
    uri_col = next((h for h in reader.fieldnames if h.lower() in ['track uri', 'spotify uri', 'uri']), None)

    if not title_col or not artist_col:
        print(f"Missing columns in {source_name}. Found title={title_col}, artist={artist_col}")
        # Return 0 to indicate failure/no inserts for this file, or we could raise exception
        return 0
    
    inserted_count = 0
    
    with Session(engine) as session:
        # Create Source - scope to user if provided
        source_query = select(Source).where(Source.name == source_name)
        if user_id:
            source_query = source_query.where(Source.user_id == user_id)
        else:
            source_query = source_query.where(Source.user_id == None)
            
        source = session.exec(source_query).first()
        if not source:
            source = Source(name=source_name, type="csv", user_id=user_id)
            session.add(source)
            session.commit()
            session.refresh(source)
        
        for row in reader:
            title = row.get(title_col)
            artist = row.get(artist_col)
            
            if title and artist:
                # Deduplication logic
                spotify_id = row.get(uri_col) if uri_col else None
                
                # 1. Check by Spotify ID if available
                existing_song = None
                if spotify_id:
                     existing_song = session.exec(select(Song).where(
                         (Song.spotify_id == spotify_id) & (Song.user_id == user_id)
                     )).first()
                
                # 2. If no ID or not found, check by Title + Artist (normalized)
                if not existing_song:
                    existing_song = session.exec(select(Song).where(
                        (Song.title == title) & (Song.artist == artist) & (Song.user_id == user_id)
                    )).first()
                
                if not existing_song:
                    song = Song(
                        title=title,
                        artist=artist,
                        source_id=source.id,
                        spotify_id=spotify_id,
                        user_id=user_id
                    )
                    session.add(song)
                    inserted_count += 1
                # Else: Skip duplicate
        
        session.commit()
    
    return inserted_count
