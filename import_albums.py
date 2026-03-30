import re
import urllib.parse
import httpx
import time
from sqlmodel import Session, select
from app.database import engine, Song, Source

# File with the list
ALBUM_FILE = "albums_1991_2000.txt"

def normalize(text):
    return text.strip()

def search_itunes_album(album, artist):
    query = f"{album} {artist}"
    params = {
        "term": query,
        "entity": "album",
        "limit": 1
    }
    url = "https://itunes.apple.com/search"
    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if data["resultCount"] > 0:
            return data["results"][0]
    except Exception as e:
        print(f"Error searching {query}: {e}")
    return None

def get_album_tracks(collection_id):
    url = "https://itunes.apple.com/lookup"
    params = {
        "id": collection_id,
        "entity": "song"
    }
    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        # Results include the collection object first, then tracks
        tracks = []
        for item in data.get("results", []):
            if item.get("wrapperType") == "track":
                tracks.append(item)
        return tracks
    except Exception as e:
        print(f"Error looking up collection {collection_id}: {e}")
        return []

def import_albums():
    with open(ALBUM_FILE, 'r') as f:
        lines = f.readlines()
    
    # Matches: "1. Album Name - Artist Name" or "1. Artist Name - Album Name" or "1. Artist Name – Album Name"
    # Using a generic separator split might be safer
    line_pattern = re.compile(r'^\d+\.\s+(.+)$')
    
    current_year = "Unknown"
    total_added = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if year header
        if re.match(r'^\d{4}$', line):
            current_year = line
            print(f"--- Processing Year: {current_year} ---")
            continue
        
        match = line_pattern.match(line)
        if not match:
            print(f"Skipping format mismatch: {line}")
            continue
            
        content = match.group(1)
        
        # Split by - or –
        parts = re.split(r'\s+[-–]\s+', content, maxsplit=1)
        
        if len(parts) < 2:
             # Fallback
            if '-' in content:
                parts = content.split('-', 1)
        
        if len(parts) < 2:
             print(f"Skipping unpresable line: {line}")
             continue

        part1 = normalize(parts[0])
        part2 = normalize(parts[1])
        
        # Heuristic: iTunes search usually works better if we don't guess wrong.
        # But we need to know for the query.
        # 1991-2000 list format seems mixed or consistently Artist - Album?
        # Let's check the user input.
        # 1991: "1. Screamadelica - Primal Scream" (Album - Artist)
        # 1991: "3. Out Of Time - Rem" (Album - Artist)
        # 1991: "16. Metallica - Metallica" (Album - Artist)
        # 1997: "1. The Verve – Urban Hymns" (Artist – Album) -> WAIT! 
        # User input 1997 line 1: "1. The Verve – Urban Hymns"
        # User input 1997 line 2: "Radiohead – Ok Computer" (Artist - Album)
        # Ah, the user switched formats again in the lists!
        # 1990-1996 seems mostly Album - Artist?
        # 1996: "1. Manic Street Preachers - Everything Must Go" (Artist - Album)
        # 1996: "2. DJ Shadow - Endtroducing" (Artist - Album)
        
        # OK, looks like the switch happens at 1996 again, similar to the song list?
        # Let's verify 1995.
        # 1995: "1. Different Class - Pulp" (Album - Artist)
        # 1995: "48. Post - Bjork" (Album - Artist)
        
        # So: < 1996: Album - Artist
        # >= 1996: Artist - Album
        
        try:
            year_int = int(current_year)
            if year_int < 1996:
                album_name = part1
                artist_name = part2
            else:
                artist_name = part1
                album_name = part2
        except:
             # Default assumption if year parsing fails
             album_name = part1
             artist_name = part2

        print(f"Processing: {album_name} by {artist_name} ({current_year})...")
        
        # 1. Search for Album
        album_data = search_itunes_album(album_name, artist_name)
        
        if not album_data:
            # Try swapping just in case?
            # print("  -> Not found. Swapping artist/album...")
            # album_data = search_itunes_album(artist_name, album_name)
            pass
            
        if not album_data:
            print(f"  -> Album not found via API.")
            continue
            
        collection_id = album_data["collectionId"]
        collection_name = album_data.get("collectionName", album_name)
        release_date = album_data.get("releaseDate", "")[:4] 
        
        # Use our list's year if available, else API
        final_year = current_year if current_year != "Unknown" else (release_date or "Unknown")
        
        print(f"  -> Found: {collection_name} (ID: {collection_id}, Year: {final_year})")
        
        # 2. Get Tracks
        tracks = get_album_tracks(collection_id)
        # print(f"  -> Found {len(tracks)} tracks.")
        
        # 3. Insert into DB
        source_name = f"Album Import: {collection_name}"
        
        with Session(engine) as session:
            source = session.exec(select(Source).where(Source.name == source_name)).first()
            if not source:
                source = Source(name=source_name, type="api_import", url=album_data.get("collectionViewUrl"))
                session.add(source)
                session.commit()
                session.refresh(source)
            
            count_for_album = 0
            for track in tracks:
                track_name = track.get("trackName")
                track_artist = track.get("artistName", artist_name) 
                
                existing = session.exec(select(Song).where(
                    (Song.title == track_name) & (Song.artist == track_artist)
                )).first()
                
                if not existing:
                    song = Song(
                        title=track_name,
                        artist=track_artist,
                        year=final_year,
                        source_id=source.id,
                        spotify_id=None
                    )
                    session.add(song)
                    count_for_album += 1
            
            session.commit()
            total_added += count_for_album
            print(f"  -> Added {count_for_album} new songs.")
            
        # Be nice to the API
        time.sleep(0.5)

    print(f"\nTotal songs added: {total_added}")

if __name__ == "__main__":
    import_albums()
