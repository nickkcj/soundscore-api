"""Gemini AI service for SoundScore chatbot."""

import re
import time
from typing import Optional

import google.generativeai as genai

from app.config import get_settings

settings = get_settings()


class GeminiService:
    """Service for interacting with Google's Gemini AI."""

    def __init__(self):
        self._configured = False
        self._model: Optional[genai.GenerativeModel] = None

    def _ensure_configured(self):
        """Configure Gemini API if not already configured."""
        if not self._configured:
            if not settings.google_api_key:
                raise ValueError("GOOGLE_API_KEY not configured")
            genai.configure(api_key=settings.google_api_key)
            self._model = genai.GenerativeModel("gemini-1.5-flash")
            self._configured = True

    def convert_prompt_to_sql(self, prompt: str, history: Optional[str] = None) -> dict:
        """Convert a natural language prompt to SQL using Gemini API."""
        self._ensure_configured()

        history_section = ""
        if history:
            history_section = f"""
### CONVERSATION HISTORY (Use this for context)
{history}
---
"""

        full_prompt = f"""You are a PostgreSQL expert. Your job is to convert user questions into clean, safe SQL queries based on the provided schema and conversation history.

### SCHEMA

**Tables** (ALWAYS use EXACTLY these table names with no schema prefixes):

- **users**
  - Columns: `id`, `username`, `email`, `created_at`, `profile_picture`, `bio`

- **reviews**
  - Columns: `id`, `rating`, `content`, `created_at`, `user_id`, `album_id`
  - Foreign Keys:
    - `user_id → users.id`
    - `album_id → albums.id`

- **albums**
  - Columns: `id`, `spotify_id`, `name`, `artist`, `image_url`, `release_date`

### FOREIGN KEY USAGE

- Use `reviews.user_id` to access user information from `users`
- Use `reviews.album_id` to access album information from `albums`
- Always use **INNER JOIN** when joining related tables through foreign keys
- You can and should follow these relationships to compute things like:
  - Review counts per album
  - Average rating per album
  - Which user wrote a specific review
  - What albums a user has reviewed, etc.

### CRITICAL RULES

- NEVER use schema prefixes like `"public."` before table names
- Output only raw SQL (no explanations, no markdown)
- Never quote numeric values (e.g. use `id = 4`, not `'4'`)
- NEVER use personal data (password, email...)
- Always use `INNER JOIN` for cross-table queries
- Use `LIMIT` where appropriate

{history_section}

### EXAMPLES

- "Show latest reviews"
`SELECT * FROM reviews ORDER BY created_at DESC LIMIT 5`

- "Show best albums"
`SELECT albums.*, AVG(reviews.rating) as avg_rating FROM albums INNER JOIN reviews ON albums.id = reviews.album_id GROUP BY albums.id ORDER BY avg_rating DESC LIMIT 5`

- "Who wrote the most reviews"
`SELECT users.username, COUNT(*) as review_count FROM reviews INNER JOIN users ON reviews.user_id = users.id GROUP BY users.id, users.username ORDER BY review_count DESC LIMIT 5`

- "What is the worst rated album"
`SELECT albums.*, AVG(reviews.rating) as avg_rating FROM albums INNER JOIN reviews ON albums.id = reviews.album_id GROUP BY albums.id ORDER BY avg_rating ASC LIMIT 1`

- "What album was reviewed the most"
`SELECT albums.name, COUNT(reviews.id) as review_count FROM albums INNER JOIN reviews ON albums.id = reviews.album_id GROUP BY albums.id, albums.name ORDER BY review_count DESC LIMIT 1`

---

USER QUESTION (Respond only to this question, using history for context):
{prompt}

---
SQL QUERY (Generate only the SQL query):
"""

        try:
            response = self._model.generate_content(full_prompt)

            if not hasattr(response, 'text') or not response.text:
                return {"sql": None, "message": "Empty response from Gemini"}

            raw_response = response.text.strip()
            sql = raw_response

            # Clean up the response - remove markdown formatting if present
            if "```" in sql:
                match = re.search(r"```(?:sql)?\s*(.*?)\s*```", sql, re.DOTALL)
                if match:
                    sql = match.group(1)

            # Remove comments and clean up whitespace
            sql = re.sub(r"--.*", "", sql)
            sql = sql.replace("\n", " ").strip()
            sql = re.sub(r"\s+", " ", sql)

            # Fix numeric values (remove quotes from numeric IDs)
            sql = re.sub(r"(\b\w*_id|\bid)\s*=\s*['\"](\d+)['\"]", r"\1 = \2", sql)
            sql = re.sub(r"(\b\w*_id|\bid)\s*=\s*['\"]?(\d+);['\"]?", r"\1 = \2", sql)

            return {"sql": sql, "message": "Generated SQL query."}

        except Exception as e:
            return {"sql": None, "message": str(e)}

    def format_results(
        self,
        results: list[dict],
        query: str,
        history: Optional[str] = None
    ) -> str:
        """Format query results using Gemini AI."""
        self._ensure_configured()

        if not results:
            return "Sorry, I could not find what you requested."

        # Filter out sensitive data
        filtered_results = self._filter_sensitive_data(results)

        history_section = ""
        if history:
            history_section = f"""
### CONVERSATION HISTORY (For context)
{history}
---
"""

        query_context = ""
        if "1 star" in query.lower() or "one star" in query.lower():
            query_context = """
IMPORTANT CONTEXT: If the results show album information, and the query was about finding albums with 1-star reviews,
then the albums in the results DO have 1-star reviews. That's why they were returned by the query.
"""

        prompt_text = f"""
{history_section}

### USER QUERY
"{query}"

### DATABASE RESULTS
{str(filtered_results)[:2000]}

{query_context}

### QUERY EXPLANATION
The database was searched based on the user's question. If results were returned, they directly answer the question.
For example:
- If the user asked about albums with 1-star reviews and album results were returned, those ARE the albums with 1-star reviews.
- If the user asked who wrote reviews and usernames were returned, those ARE the users who wrote those reviews.
- The results might not show all details, but the filtering conditions from the query have been APPLIED.

### YOUR TASK
Answer the user's question based on these results:
- Use a friendly, conversational tone
- If results were returned, they contain the answer - NEVER say you don't have information that's implied by the results
- Focus on directly answering the question using only the information provided
- If multiple items match, list them all
- Don't explain database queries or how you got the information
- Keep the response concise
"""

        try:
            response = self._model.generate_content(prompt_text)

            if not hasattr(response, 'text') or not response.text:
                return f"I found some results, but couldn't format them properly."

            return response.text.strip()

        except Exception as e:
            # Fallback to raw results
            return f"Here are the results: {str(filtered_results)[:500]}..."

    def _filter_sensitive_data(self, results: list[dict]) -> list[dict]:
        """Remove sensitive data before sending to LLM."""
        sensitive_fields = {
            'password', 'passwd', 'pass', 'hash', 'salt',
            'secret', 'token', 'api_key', 'key',
            'email', 'id', 'user_id', 'recipient_id', 'sender_id'
        }

        filtered_results = []
        for item in results:
            if isinstance(item, dict):
                filtered_item = {
                    k: v for k, v in item.items()
                    if k.lower() not in sensitive_fields
                }
                filtered_results.append(filtered_item)
            else:
                filtered_results.append(item)

        return filtered_results


    def generate_album_summary(
        self,
        title: str,
        artist: str,
        release_date: str | None,
        tracks: list[dict],
        label: str | None = None,
    ) -> str | None:
        """
        Generate a summary/description for an album using Gemini AI.

        Args:
            title: Album title
            artist: Artist name(s)
            release_date: Release date
            tracks: List of track dictionaries with 'name' key
            label: Record label (optional)

        Returns:
            Generated summary text or None if generation fails
        """
        self._ensure_configured()

        track_names = [t.get("name", "") for t in tracks[:15]]  # Limit to 15 tracks
        tracks_text = ", ".join(track_names) if track_names else "Unknown tracks"

        prompt = f"""Write a brief, engaging summary (2-3 paragraphs) about this music album.
Focus on what listeners might expect from the album based on the artist and tracklist.
Write in a neutral, informative tone suitable for a music review platform.
Do NOT invent specific facts about chart positions, sales, or awards unless you're certain.
Write in Portuguese (Brazil).

Album: {title}
Artist: {artist}
Release Date: {release_date or 'Unknown'}
Label: {label or 'Unknown'}
Tracks: {tracks_text}

Write the summary now:"""

        try:
            response = self._model.generate_content(prompt)

            if not hasattr(response, 'text') or not response.text:
                return None

            return response.text.strip()

        except Exception:
            return None


# Singleton instance
gemini_service = GeminiService()
