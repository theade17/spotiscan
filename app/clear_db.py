from sqlmodel import Session, select, delete
from app.database import engine, Song, Source

def clear_db():
    with Session(engine) as session:
        # Delete only scrape sources to preserve spotify if any (though currently none expected)
        # Actually safer to just wipe bad data.
        scrape_sources = session.exec(select(Source).where(Source.type == "scrape")).all()
        for s in scrape_sources:
            session.exec(delete(Song).where(Song.source_id == s.id))
            session.delete(s)
        session.commit()
        print("Cleared scraped data.")

if __name__ == "__main__":
    clear_db()
