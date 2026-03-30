from fastapi import FastAPI, Request, Depends, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select, or_
from .database import get_session, engine, Song, Source, User
import os
import time
import httpx
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Spotiscan")

# Session management
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "super-secret-key-123"))

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Mount static files (css, js)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def on_startup():
    from .database import create_db_and_tables
    create_db_and_tables()

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("app/static/favicon.ico")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/me")
async def get_me(request: Request, session: Session = Depends(get_session)):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"logged_in": False}
    
    user = session.get(User, user_id)
    if not user:
        return {"logged_in": False}
    
    return {
        "logged_in": True,
        "username": user.username,
        "spotify_id": user.spotify_id
    }

@app.get("/api/spotify/login")
async def spotify_login():
    scope = "user-library-read playlist-read-private"
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": scope,
        "show_dialog": "true"
    }
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{urlencode(params)}")

@app.get("/spotify-callback")
async def spotify_callback(request: Request, code: str, session: Session = Depends(get_session)):
    # Exchange code for token
    token_url = "https://accounts.spotify.com/api/token"
    auth_body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.post(token_url, data=auth_body)
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get token from Spotify")
        token_data = res.json()
        
        # Get user info
        user_res = await client.get("https://api.spotify.com/v1/me", headers={
            "Authorization": f"Bearer {token_data['access_token']}"
        })
        user_data = user_res.json()
        
    # Find or create user
    user = session.exec(select(User).where(User.spotify_id == user_data["id"])).first()
    if not user:
        user = User(
            username=user_data.get("display_name") or user_data["id"],
            spotify_id=user_data["id"]
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    
    user.access_token = token_data["access_token"]
    user.refresh_token = token_data.get("refresh_token")
    user.expires_at = time.time() + token_data["expires_in"]
    session.add(user)
    session.commit()
    
    # Store in session
    request.session["user_id"] = user.id
    
    return RedirectResponse("/")

@app.get("/api/spotify/logout")
async def spotify_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

def parse_smart_query(query_str: str):
    """
    Parses a query string into a list of includes and excludes.
    Example: 'songs with ( but not live or remix'
    -> includes: ['('], excludes: ['live', 'remix']
    """
    import re
    
    # Normalise common NL markers
    # "but not", "but do not", "without", "excluding", "not"
    query_str = re.sub(r'\b(but not|but do not|without|excluding|not)\b', ' NOT ', query_str, flags=re.IGNORECASE)
    
    parts = query_str.split(' NOT ')
    
    includes = []
    excludes = []
    
    def extract_terms_and_quotes(text):
        # Extract quoted phrases (double and single quotes)
        quotes = re.findall(r'["\']([^"\']*)["\']', text)
        # Remove quotes from string for further processing
        text_no_quotes = re.sub(r'["\'][^"\']*["\']', ' ', text)
        
        # Process remaining text for terms
        fillers = [
            'songs', 'song', 'with', 'contain', 'contains', 'containing', 
            'that', 'have', 'has', 'title', 'titles', 'character', 'characters',
            'word', 'words', 'give', 'me', 'please', 'do', 'does', 'is', 'are',
            'a', 'an', 'the', 'of', 'in', 'on', 'at'
        ]
        text_no_fillers = re.sub(r'\b(' + '|'.join(fillers) + r')\b', ' ', text_no_quotes, flags=re.IGNORECASE)
        # Split by whitespace or commas/and/or/but/any/all
        terms = re.split(r'[\s,]+|\band\b|\bor\b|\bbut\b', text_no_fillers, flags=re.IGNORECASE)
        
        return [t.strip() for t in terms if t.strip()] + [q.strip() for q in quotes if q.strip()]

    # First part is what to include
    if parts:
        includes.extend(extract_terms_and_quotes(parts[0]))
    
    # Subsequent parts are exclusions
    for et in parts[1:]:
        excludes.extend(extract_terms_and_quotes(et))
        
    return list(set(includes)), list(set(excludes))

@app.get("/api/search")
async def search_songs(
    request: Request,
    q: str = Query(..., min_length=1),
    whole_word: bool = Query(False),
    mode: str = Query("simple"), # 'simple' or 'nl'
    offset: int = Query(0, ge=0),
    limit: int = Query(25, gt=0, le=100),
    session: Session = Depends(get_session)
):
    user_id = request.session.get("user_id")
    query_str = q.strip()
    
    if mode == "nl":
        includes, excludes = parse_smart_query(query_str)
    else:
        includes = [query_str]
        excludes = []
    
    # Start building the statement
    statement = select(Song, Source).join(Source)
    
    # Filter by guest vs logged-in user
    if user_id:
        statement = statement.where(or_(Song.user_id == user_id, Song.user_id == None))
    else:
        statement = statement.where(Song.user_id == None)
    
    # Handle Inclusions
    for term in includes:
        if whole_word:
            statement = statement.where(
                or_(
                    Song.title.ilike(f"{term}"),
                    Song.title.ilike(f"{term} %"),
                    Song.title.ilike(f"% {term}"),
                    Song.title.ilike(f"% {term} %")
                )
            )
        else:
            statement = statement.where(Song.title.ilike(f"%{term}%"))
            
    # Handle Exclusions
    for term in excludes:
        statement = statement.where(Song.title.not_like(f"%{term}%"))

    # Apply sorting, offset, and limit
    statement = statement.order_by(Song.title).offset(offset).limit(limit)
    
    results = session.exec(statement).all()
    print(f"DEBUG: Found {len(results)} results for query '{query_str}' (mode={mode}, user_id={user_id})")
    
    return [
        {
            "title": song.title,
            "artist": song.artist,
            "year": song.year,
            "source": source.name,
            "source_url": source.url
        }
        for song, source in results
    ]

@app.post("/api/spotify/sync")
async def spotify_sync(request: Request, session: Session = Depends(get_session)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    
    user = session.get(User, user_id)
    if not user or not user.access_token:
        raise HTTPException(status_code=400, detail="User not authenticated with Spotify")
    
    # Check token expiry (refresh if needed is a todo, for now just try)
    if user.expires_at < time.time():
        # Token refresh logic
        pass 

    # Fetch Liked Songs (limiting to 50 for now)
    tracks_url = "https://api.spotify.com/v1/me/tracks?limit=50"
    headers = {"Authorization": f"Bearer {user.access_token}"}
    
    async with httpx.AsyncClient() as client:
        res = await client.get(tracks_url, headers=headers)
        if res.status_code != 200:
            return {"status": "error", "message": f"Spotify API error: {res.text}"}
        tracks_data = res.json()
        
    # Create or get source
    source_name = f"Spotify Liked Songs: {user.username}"
    source = session.exec(select(Source).where((Source.name == source_name) & (Source.user_id == user.id))).first()
    if not source:
        source = Source(name=source_name, type="spotify", user_id=user.id)
        session.add(source)
        session.commit()
        session.refresh(source)
    
    inserted = 0
    for item in tracks_data.get("items", []):
        track = item.get("track")
        if not track: continue
        
        title = track["name"]
        artist = ", ".join([a["name"] for a in track["artists"]])
        spotify_id = track["id"]
        
        # Check if exists for this user
        existing = session.exec(select(Song).where(
            (Song.user_id == user.id) & 
            (or_(Song.spotify_id == spotify_id, (Song.title == title) & (Song.artist == artist)))
        )).first()
        
        if not existing:
            new_song = Song(
                title=title,
                artist=artist,
                spotify_id=spotify_id,
                source_id=source.id,
                user_id=user.id
            )
            session.add(new_song)
            inserted += 1
            
    session.commit()
    return {"status": "success", "message": f"Synced {inserted} new songs from Spotify"}

from .csv_importer import process_csv
from fastapi import UploadFile, File

# ... imports ...

@app.post("/api/upload_csv")
async def upload_csv(request: Request, file: UploadFile = File(...)):
    user_id = request.session.get("user_id")
    # If not logged in, we let them upload but songs will have user_id=None (legacy)
    try:
        count = await process_csv(file, user_id=user_id)
        return {"status": "success", "message": f"Successfully imported {count} songs from {file.filename}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/sync/scrape")
async def trigger_scrape():
    # Placeholder for manual scrape trigger if needed, 
    # though scraper is currently a standalone script.
    return {"message": "Scraper must be run via command line for now."}
