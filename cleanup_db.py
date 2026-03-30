from sqlmodel import Session, select
from app.database import engine, Song

def cleanup_duplicates():
    with Session(engine) as session:
        songs = session.exec(select(Song)).all()
        print(f"Total songs before cleanup: {len(songs)}")
        
        # Sort songs: prefer those with spotify_id, then by ID (keep older/first imported)
        # We want to KEEP the best version.
        # Sorting: 
        # 1. Has Spotify ID (True > False) (Reverse=True makes True first)
        # 2. ID (Ascending? Descending? Usually keep lower ID)
        # Let's sort logic:
        # primary sort: spotify_id is not None (descending)
        # secondary sort: id (ascending)
        
        # To do mixed sort, python sort is stable.
        songs.sort(key=lambda s: s.id) # sort by ID first
        songs.sort(key=lambda s: s.spotify_id is not None, reverse=True) # then put spotify ones at top
        
        seen_keys = set()
        to_delete = []
        
        for song in songs:
            # Normalize keys
            t = song.title.strip().lower()
            a = song.artist.strip().lower()
            key = (t, a)
            
            if key in seen_keys:
                to_delete.append(song)
            else:
                seen_keys.add(key)
        
        print(f"Found {len(to_delete)} duplicates to remove.")
        
        for song in to_delete:
            session.delete(song)
            
        session.commit()
        print("Cleanup complete.")
        
        remaining = session.exec(select(Song)).all()
        print(f"Total songs after cleanup: {len(remaining)}")

if __name__ == "__main__":
    cleanup_duplicates()
