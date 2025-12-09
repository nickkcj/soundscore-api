"""Chatbot router - AI-powered database assistant."""

from fastapi import APIRouter, Query
from sqlalchemy import select, func, text, delete

from app.models.chatbot import ChatMessage
from app.schemas.chatbot import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatResponse,
    ChatHistoryResponse,
    ChatClearResponse,
)
from app.core.exceptions import BadRequestException
from app.dependencies import CurrentUser, DbSession
from app.services.gemini_service import gemini_service

router = APIRouter()

# Constants
GREETING_MESSAGE = """Hello! I'm SoundScoreBot, your database assistant.
I can help you query information about users, albums, and reviews.
What would you like to know?"""

HELP_MESSAGE = """I can answer questions about the SoundScore database. For example:
- Show me the most recent user
- Who has written the most reviews?
- What's the highest rated album?
- What is the most reviewed album?
- What is the newest album?
- What is the best review?
- What is the worst review?
- How many reviews do we have?

Just ask in plain English and I'll try to find the answer."""


async def _get_conversation_history(db: DbSession, user_id: int, limit: int = 5) -> str:
    """Get recent conversation history for context."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()

    if not messages:
        return ""

    # Build history string (oldest first)
    history_parts = []
    for msg in reversed(messages):
        history_parts.append(f"user: {msg.message}")
        history_parts.append(f"bot: {msg.response}")

    return "\n".join(history_parts)


@router.post(
    "/send",
    response_model=ChatResponse,
    summary="Send a message to the chatbot",
)
async def send_message(
    message_data: ChatMessageCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Send a message to the AI chatbot.

    The chatbot can answer questions about:
    - Users and their profiles
    - Albums and their ratings
    - Reviews and statistics
    """
    user_input = message_data.message.strip()
    user_input_lower = user_input.lower()

    # Handle special commands
    if user_input_lower in ('help', '?'):
        return ChatResponse(response=HELP_MESSAGE)

    if user_input_lower in ('hello', 'hi', 'hey', 'start'):
        return ChatResponse(response=GREETING_MESSAGE)

    if user_input_lower in ('exit', 'quit', 'bye'):
        return ChatResponse(response="Thanks for chatting! Goodbye.")

    # Get conversation history for context
    history = await _get_conversation_history(db, current_user.id)

    # Convert natural language to SQL
    query_result = gemini_service.convert_prompt_to_sql(user_input, history=history)
    sql = query_result.get("sql")

    if not sql:
        error_msg = f"I couldn't understand that query. {query_result.get('message', 'Please try rephrasing.')}"
        # Save the failed attempt
        chat_message = ChatMessage(
            user_id=current_user.id,
            message=user_input,
            response=error_msg,
        )
        db.add(chat_message)
        await db.commit()
        return ChatResponse(response=error_msg)

    # Execute the SQL query safely
    try:
        # Only allow SELECT queries for safety
        if not sql.strip().upper().startswith("SELECT"):
            raise BadRequestException("Only SELECT queries are allowed")

        result = await db.execute(text(sql))
        rows = result.fetchall()

        # Convert to list of dicts
        if rows:
            columns = result.keys()
            results = [dict(zip(columns, row)) for row in rows]
        else:
            results = []

    except Exception as e:
        error_msg = "Sorry, I could not find what you requested."
        chat_message = ChatMessage(
            user_id=current_user.id,
            message=user_input,
            response=error_msg,
        )
        db.add(chat_message)
        await db.commit()
        return ChatResponse(response=error_msg)

    # Format results with Gemini
    if not results:
        response = "Sorry, I could not find what you requested."
    else:
        response = gemini_service.format_results(results, user_input, history=history)

    # Save the conversation
    chat_message = ChatMessage(
        user_id=current_user.id,
        message=user_input,
        response=response,
    )
    db.add(chat_message)
    await db.commit()

    return ChatResponse(response=response)


@router.get(
    "/history",
    response_model=ChatHistoryResponse,
    summary="Get chat history",
)
async def get_chat_history(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get paginated chat history for the current user."""
    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(ChatMessage).where(
            ChatMessage.user_id == current_user.id
        )
    )
    total = count_result.scalar() or 0

    # Get paginated messages
    offset = (page - 1) * per_page
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    messages = result.scalars().all()

    message_responses = [
        ChatMessageResponse(
            id=m.id,
            message=m.message,
            response=m.response,
            created_at=m.created_at,
        )
        for m in messages
    ]

    return ChatHistoryResponse(
        messages=message_responses,
        total=total,
    )


@router.delete(
    "/history",
    response_model=ChatClearResponse,
    summary="Clear chat history",
)
async def clear_chat_history(
    current_user: CurrentUser,
    db: DbSession,
):
    """Clear all chat history for the current user."""
    result = await db.execute(
        delete(ChatMessage).where(ChatMessage.user_id == current_user.id)
    )
    await db.commit()

    deleted_count = result.rowcount

    return ChatClearResponse(
        message="Chat history cleared",
        deleted_count=deleted_count,
    )
