import asyncio
from app.scraper import scrape_peel_year
from app.database importcreate_db_and_tables

async def main():
    print("Starting import for 1985-1989...")
    for year in range(1985, 1990):
        print(f"--- Scraping {year} ---")
        await scrape_peel_year(year)
    print("Import complete.")

if __name__ == "__main__":
    create_db_and_tables()
    asyncio.run(main())
