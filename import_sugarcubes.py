import httpx
import time
from sqlmodel import Session, select
from app.database import engine, Song, Source

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
        tracks = []
        for item in data.get("results", []):
            if item.get("wrapperType") == "track":
                tracks.append(item)
        return tracks
    except Exception as e:
        print(f"Error looking up collection {collection_id}: {e}")
        return []

def import_sugarcubes():
    album_name = "Life's Too Good"
    artist_name = "The Sugarcubes"
    
    print(f"Processing: {album_name} by {artist_name}...")
    
    # 1. Search for Album
    album_data = search_itunes_album(album_name, artist_name)
    
    if not album_data:
        print(f"  -> Album not found via API.")
        return
        
    collection_id = album_data["collectionId"]
    collection_name = album_data.get("collectionName", album_name)
    release_date = album_data.get("releaseDate", "")[:4] 
    
    print(f"  -> Found: {collection_name} (ID: {collection_id}, Year: {release_date})")
    
    # 2. Get Tracks
    tracks = get_album_tracks(collection_id)
    print(f"  -> Found {len(tracks)} tracks.")
    
    # 3. Insert into DB
    source_name = f"Album Import: {collection_name}"
    
    total_added = 0
    with Session(engine) as session:
        source = session.exec(select(Source).where(Source.name == source_name)).first()
        if not source:
            source = Source(name=source_name, type="api_import", url=album_data.get("collectionViewUrl"))
            session.add(source)
            session.commit()
            session.refresh(source)
        
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
                    year=release_date or "1988",
                    source_id=source.id,
                    spotify_id=None
                )
                session.add(song)
                total_added += 1
                print(f"  -> Added: {track_name}")
        
        session.commit()
        print(f"Total songs added: {total_added}")

if __name__ == "__main__":
    import_sugarcubes()
