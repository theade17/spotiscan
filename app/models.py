from typing import Optional
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    spotify_id: Optional[str] = Field(default=None, unique=True)
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None # Timestamp
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    sources: list["Source"] = Relationship(back_populates="user")
    songs: list["Song"] = Relationship(back_populates="user")

class Source(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str  # e.g., "John Peel Festive 50", "Spotify Playlist"
    url: Optional[str] = None
    type: str # "scrape", "spotify", "csv"
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: Optional[User] = Relationship(back_populates="sources")
    songs: list["Song"] = Relationship(back_populates="source")

class Song(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    artist: str
    year: Optional[int] = None # Year of the chart or release
    source_id: Optional[int] = Field(default=None, foreign_key="source.id")
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    spotify_id: Optional[str] = None
    
    source: Optional[Source] = Relationship(back_populates="songs")
    user: Optional[User] = Relationship(back_populates="songs")

class Artist(SQLModel, table=True): # Optional, might keep it simple with just string in Song for now
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
