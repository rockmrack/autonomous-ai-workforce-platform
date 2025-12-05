"""
Communication Module
Handles client communications with sentiment analysis and context awareness
"""

from src.communication.handler import CommunicationHandler
from src.communication.sentiment import SentimentAnalyzer
from src.communication.memory import ConversationMemory

__all__ = ["CommunicationHandler", "SentimentAnalyzer", "ConversationMemory"]
