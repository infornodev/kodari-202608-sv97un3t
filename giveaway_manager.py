import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path


class GiveawayManager:
    def __init__(self, file_path: str = "data/giveaways.json"):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.giveaways: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.file_path.exists():
            return

        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                stored = json.load(file)
            self.giveaways = stored if isinstance(stored, dict) else {}
        except (OSError, json.JSONDecodeError):
            self.giveaways = {}

    def _save(self) -> None:
        temporary_path = self.file_path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(self.giveaways, file, indent=2)
        temporary_path.replace(self.file_path)

    def create(
        self,
        guild_id: int,
        channel_id: int,
        host_id: int,
        prize: str,
        winner_count: int,
        ends_at: datetime,
    ) -> dict:
        giveaway_id = uuid.uuid4().hex[:8].upper()
        while giveaway_id in self.giveaways:
            giveaway_id = uuid.uuid4().hex[:8].upper()

        giveaway = {
            "id": giveaway_id,
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "message_id": None,
            "host_id": str(host_id),
            "prize": prize,
            "winner_count": winner_count,
            "ends_at": ends_at.astimezone(timezone.utc).isoformat(),
            "status": "active",
            "bonus_entries": {},
            "winner_ids": [],
        }
        self.giveaways[giveaway_id] = giveaway
        self._save()
        return giveaway.copy()

    def attach_message(self, giveaway_id: str, message_id: int) -> dict | None:
        giveaway = self.giveaways.get(giveaway_id.upper())
        if giveaway is None:
            return None
        giveaway["message_id"] = str(message_id)
        self._save()
        return giveaway.copy()

    def get(self, giveaway_id: str) -> dict | None:
        giveaway = self.giveaways.get(giveaway_id.upper())
        return giveaway.copy() if giveaway else None

    def active(self) -> list[dict]:
        return [giveaway.copy() for giveaway in self.giveaways.values() if giveaway["status"] == "active"]

    def due(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        due_giveaways = []
        for giveaway in self.active():
            ends_at = datetime.fromisoformat(giveaway["ends_at"])
            if ends_at <= now:
                due_giveaways.append(giveaway)
        return due_giveaways

    def add_bonus_entries(self, giveaway_id: str, user_id: int, amount: int) -> dict | None:
        giveaway = self.giveaways.get(giveaway_id.upper())
        if giveaway is None or giveaway["status"] != "active":
            return None

        user_key = str(user_id)
        entries = giveaway["bonus_entries"]
        entries[user_key] = int(entries.get(user_key, 0)) + amount
        self._save()
        return giveaway.copy()

    def choose_winners(
        self,
        giveaway_id: str,
        participant_ids: list[int],
        excluded_ids: list[int] | None = None,
    ) -> list[str]:
        giveaway = self.giveaways.get(giveaway_id.upper())
        if giveaway is None:
            return []

        excluded = {str(user_id) for user_id in (excluded_ids or [])}
        available = {}
        for user_id in participant_ids:
            user_key = str(user_id)
            if user_key not in excluded:
                available[user_key] = 1 + int(giveaway["bonus_entries"].get(user_key, 0))

        winners = []
        generator = random.SystemRandom()
        while available and len(winners) < giveaway["winner_count"]:
            total_weight = sum(available.values())
            selected_point = generator.randrange(total_weight)
            for user_id, weight in available.items():
                if selected_point < weight:
                    winners.append(user_id)
                    del available[user_id]
                    break
                selected_point -= weight
        return winners

    def finish(self, giveaway_id: str, winner_ids: list[int | str]) -> dict | None:
        giveaway = self.giveaways.get(giveaway_id.upper())
        if giveaway is None:
            return None

        giveaway["status"] = "ended"
        giveaway["winner_ids"] = [str(user_id) for user_id in winner_ids]
        self._save()
        return giveaway.copy()