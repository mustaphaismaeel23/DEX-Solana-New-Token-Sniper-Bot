"""
Twitter/X social signal analysis for token utility scoring.
Analyzes project presence, community engagement, and sentiment on Twitter.
"""
import logging
import time
import httpx
import re
from config import settings

log = logging.getLogger("twitter_signals")

TWITTER_API_BASE = "https://api.twitter.com/2"
HEADERS = {
    "Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}",
    "User-Agent": "SniperBot/1.0"
}


async def extract_twitter_handle(text: str) -> str | None:
    """Extract Twitter handle from text (website, description, etc)."""
    if not text:
        return None
    # Look for @handle pattern
    match = re.search(r'@([a-zA-Z0-9_]{1,15})', text)
    if match:
        return match.group(1)
    # Look for twitter.com/username pattern
    match = re.search(r'(?:twitter|x)\.com/([a-zA-Z0-9_]{1,15})', text)
    if match:
        return match.group(1)
    return None


async def get_twitter_user_stats(client: httpx.AsyncClient, username: str) -> dict | None:
    """Fetch Twitter user stats: followers, engagement, etc."""
    if not settings.TWITTER_BEARER_TOKEN:
        return None
    
    try:
        # Get user info
        user_response = await client.get(
            f"{TWITTER_API_BASE}/users/by/username/{username}",
            headers=HEADERS,
            params={
                "user.fields": "public_metrics,created_at,verified,description,followers_count,following_count",
                "expansions": "author_id"
            },
            timeout=10
        )
        user_response.raise_for_status()
        user_data = user_response.json()
        
        if "errors" in user_data or not user_data.get("data"):
            return None
        
        user = user_data["data"]
        metrics = user.get("public_metrics", {})
        
        return {
            "username": username,
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "tweet_count": metrics.get("tweet_count", 0),
            "verified": user.get("verified", False),
            "created_at": user.get("created_at"),
            "description": user.get("description", ""),
        }
    except Exception as e:
        log.warning(f"Failed to fetch Twitter stats for @{username}: {e}")
        return None


async def analyze_token_tweets(client: httpx.AsyncClient, query: str, limit: int = 100) -> dict:
    """Analyze recent tweets about a token for sentiment and engagement."""
    if not settings.TWITTER_BEARER_TOKEN:
        return {"tweet_count": 0, "avg_engagement": 0, "sentiment_score": 0}
    
    try:
        # Search for recent tweets mentioning the token
        search_response = await client.get(
            f"{TWITTER_API_BASE}/tweets/search/recent",
            headers=HEADERS,
            params={
                "query": f"{query} -is:retweet lang:en",
                "max_results": min(limit, 100),
                "tweet.fields": "public_metrics,created_at,author_id,lang",
                "expansions": "author_id",
                "user.fields": "public_metrics,verified"
            },
            timeout=15
        )
        search_response.raise_for_status()
        data = search_response.json()
        
        tweets = data.get("tweets", [])
        includes = data.get("includes", {})
        users_by_id = {u["id"]: u for u in includes.get("users", [])}
        
        if not tweets:
            return {"tweet_count": 0, "avg_engagement": 0, "sentiment_score": 0, "evidence": []}
        
        # Analyze engagement and sentiment
        total_engagement = 0
        positive_sentiment_count = 0
        evidence = []
        verified_mentions = 0
        
        for tweet in tweets:
            metrics = tweet.get("public_metrics", {})
            likes = metrics.get("like_count", 0)
            retweets = metrics.get("retweet_count", 0)
            replies = metrics.get("reply_count", 0)
            total_engagement += likes + retweets + replies
            
            # Check if author is verified (higher credibility)
            author_id = tweet.get("author_id")
            if author_id and author_id in users_by_id:
                author = users_by_id[author_id]
                if author.get("verified"):
                    verified_mentions += 1
            
            # Simple sentiment: look for positive/negative keywords
            text = tweet.get("text", "").lower()
            positive_keywords = ["bullish", "moon", "diamond", "gem", "potential", "buy", "amazing", "great"]
            negative_keywords = ["bearish", "rug", "scam", "dump", "sell", "dead", "loss"]
            
            pos_count = sum(1 for kw in positive_keywords if kw in text)
            neg_count = sum(1 for kw in negative_keywords if kw in text)
            
            if pos_count > neg_count:
                positive_sentiment_count += 1
        
        avg_engagement = total_engagement / len(tweets) if tweets else 0
        sentiment_score = (positive_sentiment_count / len(tweets) * 100) if tweets else 0
        
        if verified_mentions > 0:
            evidence.append(f"{verified_mentions} verified accounts mentioning")
        if sentiment_score > 60:
            evidence.append(f"positive sentiment {sentiment_score:.0f}%")
        
        return {
            "tweet_count": len(tweets),
            "avg_engagement": avg_engagement,
            "sentiment_score": sentiment_score,
            "verified_mentions": verified_mentions,
            "evidence": evidence
        }
    except Exception as e:
        log.warning(f"Failed to analyze tweets for '{query}': {e}")
        return {"tweet_count": 0, "avg_engagement": 0, "sentiment_score": 0}


async def check_twitter_signals(client: httpx.AsyncClient, token_name: str, 
                                token_symbol: str, pair_info: dict | None = None) -> tuple[dict, str]:
    """
    Check Twitter signals for a token. Returns (scores_dict, evidence_string).
    
    Returns dict with:
    - twitter_found: bool
    - followers: int
    - engagement_score: float (0-100)
    - sentiment_score: float (0-100)
    - verified: bool
    - total_points: int (0-40)
    """
    if not settings.ENABLE_TWITTER_SIGNALS:
        return {"twitter_found": False, "total_points": 0}, "Twitter analysis disabled"
    
    scores = {
        "twitter_found": False,
        "followers": 0,
        "engagement_score": 0,
        "sentiment_score": 0,
        "verified": False,
        "total_points": 0
    }
    evidence_parts = []
    
    # Extract Twitter handle from pair info if available
    twitter_handle = None
    if pair_info:
        info = pair_info.get("info", {})
        socials = info.get("socials", [])
        
        # Look for Twitter in socials
        for social in socials:
            if isinstance(social, dict):
                if social.get("type") == "twitter":
                    twitter_handle = social.get("url", "").split("/")[-1]
                    break
            elif isinstance(social, str) and "twitter" in social.lower():
                twitter_handle = extract_twitter_handle(social)
                if twitter_handle:
                    break
    
    # Try to extract from token name/symbol if not found
    if not twitter_handle:
        twitter_handle = extract_twitter_handle(token_name) or extract_twitter_handle(token_symbol)
    
    # If still not found, search for it
    if not twitter_handle:
        # Try searching by token symbol
        search_query = token_symbol.replace("pump", "").strip()
        if len(search_query) > 2:
            twitter_handle = search_query
    
    if not twitter_handle:
        if settings.REQUIRE_TWITTER_PRESENCE:
            return scores, "No Twitter account found (required)"
        return scores, "No Twitter account found"
    
    # Fetch user stats
    user_stats = await get_twitter_user_stats(client, twitter_handle)
    if not user_stats:
        if settings.REQUIRE_TWITTER_PRESENCE:
            return scores, f"Could not fetch @{twitter_handle} Twitter stats"
        return scores, f"Could not fetch @{twitter_handle} stats"
    
    scores["twitter_found"] = True
    scores["followers"] = user_stats.get("followers", 0)
    scores["verified"] = user_stats.get("verified", False)
    
    # Score based on followers
    followers_score = min(30, (user_stats.get("followers", 0) / max(settings.MIN_TWITTER_FOLLOWERS, 100)) * 15)
    
    # Score for verified status
    verified_bonus = 10 if scores["verified"] else 0
    
    # Analyze recent tweets
    tweet_analysis = await analyze_token_tweets(client, f"${token_symbol} OR {token_name}", limit=50)
    scores["sentiment_score"] = tweet_analysis.get("sentiment_score", 0)
    
    # Engagement score based on tweet metrics
    avg_engagement = tweet_analysis.get("avg_engagement", 0)
    engagement_score = min(10, (avg_engagement / max(10, settings.MIN_TWITTER_ENGAGEMENT_RATE)) * 5)
    scores["engagement_score"] = engagement_score
    
    # Tweet volume bonus
    tweet_volume_bonus = 5 if tweet_analysis.get("tweet_count", 0) > 5 else 0
    
    # Calculate total points
    total_points = followers_score + verified_bonus + engagement_score + tweet_volume_bonus
    
    # Apply sentiment penalty if too negative
    if scores["sentiment_score"] < 30:
        total_points *= 0.5  # Reduce score if mostly negative sentiment
    
    scores["total_points"] = int(total_points)
    
    # Build evidence string
    if scores["followers"] >= settings.MIN_TWITTER_FOLLOWERS:
        evidence_parts.append(f"@{twitter_handle} ({scores['followers']} followers)")
    
    if scores["verified"]:
        evidence_parts.append("✓ verified")
    
    if tweet_analysis.get("tweet_count", 0) > 0:
        evidence_parts.append(f"{tweet_analysis['tweet_count']} recent tweets")
    
    if scores["sentiment_score"] > 60:
        evidence_parts.append(f"positive sentiment {scores['sentiment_score']:.0f}%")
    
    if tweet_analysis.get("verified_mentions", 0) > 0:
        evidence_parts.append(f"{tweet_analysis['verified_mentions']} verified mentions")
    
    evidence = ", ".join(evidence_parts) if evidence_parts else "Twitter presence confirmed"
    
    return scores, evidence
