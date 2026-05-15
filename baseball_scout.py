import os
import json
import datetime
import requests
import statsapi
from google import genai
from espn_api.baseball import League

# 1. SETUP & PERSISTENCE
TRACKER_FILE = 'tracked_players.json'
TODAY = datetime.date.today().strftime('%Y-%m-%d')
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

def load_memory():
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, 'r') as f:
            return json.load(f)
    return {"watching": [], "last_run": ""}

def save_memory(data):
    with open(TRACKER_FILE, 'w') as f:
        json.dump(data, f)

# 2. DATA GATHERING
def get_scouting_data():
    memory = load_memory()
    
    # A. Check Yesterday's Rookie Performances
    past_results = []
    for p_id in memory.get("watching", []):
        try:
            # Get the boxscore for the player's last game
            last_game = statsapi.last_game(p_id)
            if last_game:
                box = statsapi.boxscore_data(last_game)
                past_results.append({"id": p_id, "stats": box})
        except:
            continue

    # B. Identify Today's Potential Debuts
    upcoming_debuts = []
    schedule = statsapi.schedule(date=TODAY)
    for game in schedule:
        for p_key in ['home_probable', 'away_probable']:
            p_name = game.get(p_key)
            if p_name:
                search = statsapi.lookup_player(p_name)
                if search:
                    p_id = search[0]['id']
                    # Simplified debut check: fetch career stats
                    career = statsapi.player_stat_data(p_id, group="pitching", type="career")
                    if not career.get('stats') or career['stats'][0]['stat']['gamesPlayed'] < 3:
                        upcoming_debuts.append({"id": p_id, "name": p_name})

    # C. Get ESPN League Free Agents (Filtered for Ownership)
    league = League(league_id=os.getenv('LEAGUE_ID'), 
                    year=2026, 
                    espn_s2=os.getenv('ESPN_S2'), 
                    swid=os.getenv('ESPN_SWID'))
    
    # Get top 150 available players to ensure we find the "hidden gems"
    fa_list = league.free_agents(size=150)
    fa_names = [p.name for p in fa_list]

    # D. Fetch League-Wide Hot Streaks (Last 15 Days)
    try:
        # Standard OPS leaders (Reliable API key)
        hot_hitters = statsapi.league_leaders('onBasePlusSlugging', statGroup='hitting', limit=15)
    except Exception as e:
        print(f"Error fetching hitting leaders: {e}")
        hot_hitters = []

    # Get Exit Velocity Leaders (Pure Power)
    # This finds the players hitting the ball the hardest right now
    try:
        # Standard Home Run leaders to capture pure power
        hard_hitters = statsapi.league_leaders('homeRuns', statGroup='hitting', limit=10)
    except Exception as e:
        print(f"Error fetching power leaders: {e}")
        hard_hitters = []
    
    return {
        "yesterday_review": past_results,
        "today_debuts": upcoming_debuts,
        "hot_hitters": hot_hitters,
        "free_agents": fa_names,
        "hard_hitters": hard_hitters
    }

# 3. AI ANALYSIS & DELIVERY
def run_report():
    data = get_scouting_data()
    
    # Construct the Scouting Prompt
    prompt = f"""
    Context: We are currently in the 2026 MLB regular season. You are an elite, cutthroat Fantasy Baseball Scout.
    Objective: Help me find high-upside players to add from Free Agency BEFORE my opponents notice them.
    
    RAW DATA:
    1. Yesterday's Rookie Results: {data['yesterday_review']}
    2. Today's Debut Pitchers: {data['today_debuts']}
    3. MLB Hot Streaks (Recent OPS Leaders): {data['hot_hitters']}
    4. MLB Power Leaders (Recent HR Leaders): {data['hard_hitters']}
    5. MY LEAGUE'S FREE AGENTS: {data['free_agents']}
    
    INSTRUCTIONS:
    - ONLY recommend players who are currently listed in my 'FREE AGENTS' pool. If a player is hot but already owned, completely ignore them.
    - Look at yesterday's rookie box scores and issue a definitive 'Buy' or 'Sell' verdict on whether they are worth stashing long-term or if they were just a flash in the pan.
    - Highlight upcoming rookie pitchers scheduled for today who are unowned, detailing their streaming viability.
    - Cross-reference the Hot Streaks and Power Leaders with my Free Agents. Identify one 'Deep Sleeper' on a sneaky hot streak or an unowned power source that my opponents are completely ignoring.
    - Use a sharp, professional, highly analytical scout tone. Do not mention superstars who are obviously owned.
    """
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    response =  client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    # Send to Discord
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    requests.post(webhook_url, json={"content": response.text})

    # Update Memory for Tomorrow
    new_memory = {
        "watching": [p['id'] for p in data['today_debuts']],
        "last_run": TODAY
    }
    save_memory(new_memory)

if __name__ == "__main__":
    run_report()
