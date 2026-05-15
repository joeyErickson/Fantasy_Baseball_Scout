import os
import json
import datetime
import requests
import statsapi
import google.generativeai as genai
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
    hot_hitters = statsapi.league_leaders('weightedOnBaseAverage', statGroup='hitting', limit=10)

    # Get Exit Velocity Leaders (Pure Power)
    # This finds the players hitting the ball the hardest right now
    hard_hitters = statsapi.league_leaders('avgExitVelocity', statGroup='hitting', limit=10)
    
    return {
        "yesterday_review": past_results,
        "today_debuts": upcoming_debuts,
        "hot_hitters": hot_hitters,
        "free_agents": fa_names,
        "exit velo": hard_hitters
    }

# 3. AI ANALYSIS & DELIVERY
def run_report():
    data = get_scouting_data()
    
    # Construct the Scouting Prompt
    prompt = f"""
    Context:  You are an elite Fantasy Baseball Scout for the current date today.
    Objective: Help me find high-upside players to add from Free Agency BEFORE my opponents.
    
    RAW DATA:
    1. Yesterday's Rookie Results: {data['yesterday_review']}
    2. Today's Debut Pitchers: {data['today_debuts']}
    3. MLB Hot Streaks: {data['hot_hitters']}
    4. MY LEAGUE'S FREE AGENTS: {data['free_agents']}
    
    INSTRUCTIONS:
    - ONLY recommend players who are in my 'FREE AGENTS' list.
    - If a hot hitter is already owned, ignore them.
    - For yesterday's rookies, give a 'Buy' or 'Sell' verdict based on their box score.
    - Mention one 'Deep Sleeper' that my opponents are likely ignoring.
    - Use a sharp, professional scout tone.
    """

    genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    
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