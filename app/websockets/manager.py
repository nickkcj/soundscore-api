import json
from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    """
    WebSocket connection manager for group chat.

    Manages connections per group and handles broadcasting messages.
    """

    def __init__(self):
        # group_id -> set of (user_id, websocket) tuples
        self.active_connections: Dict[int, Dict[int, WebSocket]] = {}
        # user_id -> set of group_ids (track which groups user is connected to)
        self.user_groups: Dict[int, Set[int]] = {}

    async def connect(self, websocket: WebSocket, group_id: int, user_id: int):
        """Register a WebSocket connection (must be already accepted)."""
        # Add to group connections
        if group_id not in self.active_connections:
            self.active_connections[group_id] = {}
        self.active_connections[group_id][user_id] = websocket

        # Track user's groups
        if user_id not in self.user_groups:
            self.user_groups[user_id] = set()
        self.user_groups[user_id].add(group_id)

    def disconnect(self, group_id: int, user_id: int):
        """Remove a WebSocket connection."""
        if group_id in self.active_connections:
            self.active_connections[group_id].pop(user_id, None)
            if not self.active_connections[group_id]:
                del self.active_connections[group_id]

        if user_id in self.user_groups:
            self.user_groups[user_id].discard(group_id)
            if not self.user_groups[user_id]:
                del self.user_groups[user_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific connection."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            pass

    async def broadcast_to_group(self, group_id: int, message: dict, exclude_user_id: int = None):
        """Broadcast a message to all users in a group."""
        if group_id not in self.active_connections:
            return

        message_text = json.dumps(message)
        for user_id, websocket in self.active_connections[group_id].items():
            if exclude_user_id and user_id == exclude_user_id:
                continue
            try:
                await websocket.send_text(message_text)
            except Exception:
                pass

    def get_online_users(self, group_id: int) -> list[int]:
        """Get list of online user IDs in a group."""
        if group_id not in self.active_connections:
            return []
        return list(self.active_connections[group_id].keys())

    def is_user_online(self, group_id: int, user_id: int) -> bool:
        """Check if a user is online in a group."""
        if group_id not in self.active_connections:
            return False
        return user_id in self.active_connections[group_id]

    def get_connection_count(self, group_id: int) -> int:
        """Get number of connections in a group."""
        if group_id not in self.active_connections:
            return 0
        return len(self.active_connections[group_id])


# Singleton instance
manager = ConnectionManager()
