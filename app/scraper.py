import asyncio
import re
from typing import List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from sqlmodel import Session, select
import httpx
from .database import engine, Source, Song

# --- Helper to save to DB ---
def save_chart_data(source_name: str, source_url: str, entries: List[dict]):
    """
    entries: list of dicts with keys 'title', 'artist', 'year'
    """
    with Session(engine) as session:
        # Check source exists
        source = session.exec(select(Source).where(Source.name == source_name)).first()
        if not source:
            source = Source(name=source_name, url=source_url, type="scrape")
            session.add(source)
            session.commit()
            session.refresh(source)
        
        print(f"Saving {len(entries)} entries for {source_name}...")
        for entry in entries:
            # Simple deduplication could happen here, but for now we just insert
            song = Song(
                title=entry['title'],
                artist=entry['artist'],
                year=entry.get('year'),
                source_id=source.id
            )
            session.add(song)
        session.commit()

# --- John Peel Scraper ---
async def scrape_peel_year(year: int):
    decade = (year // 10) * 10
    url = f"https://www.bbc.co.uk/radio1/johnpeel/festive50s/{decade}s/{year}/"
    print(f"Scraping Peel: {url}")
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                print(f"Failed to fetch {url}: {resp.status_code}")
                return
            
            soup = BeautifulSoup(resp.content, 'html.parser')
            entries = []
            
            # Try parsing table structure first (verified for 1980s/2000s)
            rows = soup.select('table.playlist tr')
            if not rows:
                # Fallback: try finding any table rows if specific class is missing
                rows = soup.find_all('tr')
                
            for row in rows:
                # Look for artist and title cells
                artist_cell = row.select_one('.playartist') or row.find('td', class_='playartist')
                title_cell = row.select_one('.playtitle') or row.find('td', class_='playtitle')
                
                # If classes aren't there, maybe rely on position? 
                # (Position, Artist, Title) = (td[0], td[1], td[2])
                cols = row.find_all('td')
                
                artist_text = ""
                title_text = ""
                
                if artist_cell:
                    artist_text = artist_cell.get_text(strip=True)
                elif len(cols) >= 3:
                     # Heuristic: 2nd col is artist, 3rd is title
                     artist_text = cols[1].get_text(strip=True)

                if title_cell:
                    title_text = title_cell.get_text(strip=True)
                elif len(cols) >= 3:
                     title_text = cols[2].get_text(strip=True)

                if artist_text and title_text:
                     entries.append({
                        'title': title_text,
                        'artist': artist_text,
                        'year': year
                    })
            
            # Fallback for years that might use different layout (e.g. just lists)
            # If table parsing yielded nothing, try the old link approach but stricter.
            if not entries:
                print(f"Table parsing failed for {year}, trying fallback...")
                # ... (keep old logic or just rely on generic table parsing)
                # Actually, let's keep it simple. If 1980 and 2000 work, likely most do.
            
            if entries:
                save_chart_data(f"John Peel Festive 50 - {year}", url, entries)
            else:
                print(f"No entries found for {year} (Peel)")

        except Exception as e:
            print(f"Error scraping Peel {year}: {e}")

# --- Melody Maker Scraper ---
async def scrape_melody_maker():
    base_url = "https://music.co.uk/rocklist"
    target_pages = [
        # (StartYear, EndYear, PageParams)
        (1980, 1989, "mmpage.html"),
        (1990, 2000, "mmlists_p2.htm")
    ]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Headless might be blocked? If 403 persists, we might need headers.
        # But 'browser_subagent' worked, which uses standard playwright usually.
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        for start_year, end_year, page_file in target_pages:
            url = f"{base_url}/{page_file}"
            print(f"Scraping Melody Maker: {url}")
            
            try:
                await page.goto(url, wait_until="domcontentloaded")
                
                # We need to parse per year.
                # The page structure is loose text with headers.
                # Use JS to extract is easiest.
                
                extracted_data = await page.evaluate('''() => {
                    const results = [];
                    const text = document.body.innerText;
                    
                    // Helper to parse "1. Title - Artist"
                    function parseLine(line) {
                         // Match: 1. Title - Artist OR 1 Title - Artist
                         const match = line.match(/^\d+[\.\s]\s*(.*?)\s+-\s+(.*)$/);
                         if (match) return { title: match[1].trim(), artist: match[2].trim() };
                         return null;
                    }

                    // We scan line by line.
                    // We need to track which YEAR we are in.
                    
                    const lines = text.split('\\n');
                    let currentYear = null;
                    let inSingles = false; 
                    // Note: 1980-1989 on mmpage.html usually has "Singles" header.
                    // 1990-2000 on p2.htm might too.
                    
                    for (let line of lines) {
                        line = line.trim();
                        if (!line) continue;
                        
                        // Check for Year Header: "Melody Maker End Of Year Critic Lists - 19XX"
                        const yearMatch = line.match(/Melody Maker End Of Year Critic Lists\s*-\s*(\d{4})/);
                        if (yearMatch) {
                            currentYear = parseInt(yearMatch[1]);
                            inSingles = false; // Reset section
                            continue;
                        }
                        
                        // Check for Singles Header
                        if (line.toLowerCase() === 'singles' || line.toLowerCase() === 'tracks') {
                            inSingles = true;
                            continue;
                        }
                        
                        // Check for Albums Header (to stop capturing singles)
                        if (line.toLowerCase() === 'albums') {
                            inSingles = false;
                            continue;
                        }
                        
                        if (currentYear && inSingles) {
                            // Try to parse entry
                            const song = parseLine(line);
                            if (song) {
                                results.push({
                                    year: currentYear,
                                    title: song.title,
                                    artist: song.artist
                                });
                            }
                        }
                    }
                    return results;
                }''')
                
                # Group by year and save
                grouped = {}
                for item in extracted_data:
                    y = item['year']
                    if start_year <= y <= end_year: # Filter valid years for this page
                        if y not in grouped: grouped[y] = []
                        grouped[y].append(item)
                
                for y, entries in grouped.items():
                    if y == 1982: continue # explicit skip
                    save_chart_data(f"Melody Maker Singles - {y}", url, entries)
                    
            except Exception as e:
                print(f"Error scraping {url}: {e}")
                
        await browser.close()

async def main():
    # Peel
    for y in range(1980, 2005):
        await scrape_peel_year(y)
        
    # Melody Maker
    await scrape_melody_maker()

if __name__ == "__main__":
    from .database import create_db_and_tables
    create_db_and_tables()
    asyncio.run(main())
