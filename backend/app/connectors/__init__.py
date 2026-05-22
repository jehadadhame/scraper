from app.connectors.discord import DiscordConnector
from app.connectors.facebook import FacebookConnector
from app.connectors.news import NewsConnector
from app.connectors.telegram import TelegramConnector


def build_connectors() -> dict[str, object]:
    return {
        "telegram": TelegramConnector(),
        "discord": DiscordConnector(),
        "facebook": FacebookConnector(),
        "news": NewsConnector(),
    }

