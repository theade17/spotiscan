import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv

load_dotenv()

def get_spotify_client():
    # Only return client if credentials are set
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    
    if not client_id or "your_client_id" in client_id:
        return None

    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/callback"),
        scope="playlist-read-private user-library-read"
    ))

def fetch_user_playlists(sp):
    results = sp.current_user_playlists()
    playlists = []
    while results:
        for i, item in enumerate(results['items']):
            playlists.append({
                'id': item['id'],
                'name': item['name'],
                'url': item['external_urls']['spotify']
            })
        if results['next']:
            results = sp.next(results)
        else:
            results = None
    return playlists

def fetch_playlist_tracks(sp, playlist_id):
    results = sp.playlist_tracks(playlist_id)
    tracks = []
    # Pagination could be added here, simplified for now
    for item in results['items']:
        track = item['track']
        if track:
            tracks.append({
                'title': track['name'],
                'artist': ", ".join([artist['name'] for artist in track['artists']]),
                'spotify_id': track['id']
            })
    return tracks
