"""
上下文管理模块 - 负责管理对话上下文、计算令牌数量并在需要时生成摘要
"""

import json
import datetime
import os
import sys
from typing import List, Dict, Any, Optional, Tuple, Callable
from datetime import timezone

from utils import logger
from utils.config import config
import tiktoken
import asyncio
from datetime import datetime, timezone

# Import litellm for accurate token counting and cost calculation
import litellm

from agent.core.persistence_manager import PersistenceManager # Import PM

# Constants for token management
DEFAULT_TOKEN_THRESHOLD = 120000  # Trigger summarization above 120k tokens
SUMMARY_TARGET_TOKENS = 10000    # Target ~10k tokens for the summary message
RESERVE_TOKENS = config.RESERVE_TOKENS  # Reserve tokens for new messages + system prompt

class ContextManager:
    """Manages conversation context, including history truncation and summarization."""
    
    def __init__(self, token_threshold: int = DEFAULT_TOKEN_THRESHOLD):
        """Initialize the ContextManager.
        
        Args:
            token_threshold: Token count threshold to trigger summarization.
        """
        self.token_threshold = token_threshold
        self.make_llm_api_call = None
        self.persistence_manager: Optional[PersistenceManager] = None

    def set_llm_api_caller(self, caller: Callable):
        """Set the function used to make LLM API calls for summarization."""
        self.make_llm_api_call = caller

    def set_persistence_manager(self, pm: PersistenceManager):
        """Inject the PersistenceManager instance."""
        self.persistence_manager = pm

    def get_token_counter(self) -> Callable:
        """Returns the token counting function used by this manager."""
        return self._count_tokens

    def _count_tokens(self, messages: List[Dict[str, Any]], model: str = "gpt-4") -> int:
        """Counts tokens using litellm for a list of messages."""
        if not messages:
            return 0
        try:
            # Ensure messages are in the correct format for litellm
            formatted_messages = []
            for msg in messages:
                # Basic format check, adapt if needed based on actual message structure
                role = msg.get('role')
                content = msg.get('content')
                if role and content is not None:
                     # Handle potential list content (e.g., images + text)
                    if isinstance(content, list):
                         # LiteLLM handles list content directly
                         formatted_messages.append({"role": role, "content": content})
                    elif isinstance(content, str):
                         formatted_messages.append({"role": role, "content": content})
                    else:
                         # Attempt to stringify other types, might need refinement
                         try:
                            formatted_messages.append({"role": role, "content": json.dumps(content)})
                         except Exception:
                             logger.warning(f"Could not format message content for token counting: {content}")
                elif isinstance(msg, str): # Handle raw string messages if they exist
                     logger.warning(f"Found raw string message, attempting to count as user message: {msg}")
                     formatted_messages.append({"role": "user", "content": msg})

            if not formatted_messages:
                logger.warning("No valid messages found to count tokens.")
                return 0

            # Use litellm's token_counter
            return litellm.token_counter(model=model, messages=formatted_messages)
        except Exception as e:
            logger.error(f"Error counting tokens with litellm: {e}", exc_info=True)
            # Fallback or re-raise? For now, return 0 or a high number? Let's return 0.
            return 0

    async def get_thread_token_count(self, thread_id: str, model: str = "gpt-4") -> int:
        """Get the current token count for a thread using LiteLLM.
        
        Args:
            thread_id: ID of the thread to analyze.
            model: The model name to use for token counting (important for accuracy).
            
        Returns:
            The total token count for relevant messages in the thread.
        """
        logger.debug(f"Getting token count for thread {thread_id} using model {model}")
        try:
            # Get messages relevant for token counting (usually all since last summary)
            messages = await self.get_messages_for_summarization(thread_id)
            if not messages:
                logger.debug(f"No messages found for token count for thread {thread_id}")
                return 0

            token_count = self._count_tokens(messages, model=model)
            logger.info(f"Thread {thread_id} has approximately {token_count} tokens (calculated with litellm).")
            return token_count

        except Exception as e:
            logger.error(f"Error getting thread token count for {thread_id}: {e}", exc_info=True)
            return 0 # Return 0 to avoid accidental summarization on error

    async def get_messages_for_summarization(self, thread_id: str) -> List[Dict[str, Any]]:
        """Get all LLM-relevant messages from the thread since the last summary."""
        if not self.persistence_manager:
            logger.error("PersistenceManager not set in ContextManager!")
            return []
        logger.debug(f"CM: Getting messages for summarization for {thread_id}")
        try:
            # Use PersistenceManager method
            last_summary_time = self.persistence_manager.get_last_summary_timestamp(thread_id)

            if last_summary_time:
                logger.debug(f"CM: Found last summary at {last_summary_time}. Fetching messages after.")
                # Use PersistenceManager method
                raw_messages = self.persistence_manager.get_messages_after_timestamp(thread_id, last_summary_time)
            else:
                logger.debug("CM: No previous summary found, getting all messages.")
                # Use PersistenceManager method
                raw_messages = self.persistence_manager.get_all_messages(thread_id)

            # Process raw messages into the format needed for LLM
            processed_messages = []
            for msg in raw_messages:
                role = msg.get('role'); content_str = msg.get('content'); metadata = msg.get('metadata', {})
                if metadata.get('is_summary'): continue # Skip summary messages
                try: content = json.loads(content_str) if isinstance(content_str, str) and (content_str.startswith('{') or content_str.startswith('[')) else content_str
                except json.JSONDecodeError: content = content_str
                if role == 'tool_output': # Convert tool output role
                    role = 'assistant'
                    content = f"[工具执行结果] {content}" if isinstance(content, str) else content
                if role and content is not None:
                    processed_messages.append({"role": role, "content": content})
                else:
                    logger.warning(f"CM: Skipping msg {msg.get('message_id')} due to missing role/content.")
            logger.info(f"CM: Got {len(processed_messages)} messages to potentially summarize for {thread_id}")
            return processed_messages
        except Exception as e:
            logger.error(f"CM: Error getting messages for summarization: {str(e)}", exc_info=True)
            return []

    async def get_optimal_context(
        self,
        thread_id: str,
        system_prompt: Dict[str, Any],
        max_context_tokens: int, # Total token limit for the prompt
        model: str = "gpt-4",
        add_message_callback: Optional[Callable] = None, # Needed for summarization check
        force_summarize: bool = False # Option to force summarization on this call
    ) -> List[Dict[str, Any]]:
        """Get the optimal context for an LLM call based on token limits.
        
        Args:
            thread_id: Thread ID to get context for.
            system_prompt: System prompt message dictionary.
            max_context_tokens: Maximum tokens to allow in context (default: model limit).
            model: Model name for token counting.
            add_message_callback: Callback to add message to database (for summary).
            force_summarize: Whether to force summarization this time.
            
        Returns:
            List of messages optimized for context.
        """
        if not self.persistence_manager:
            logger.error("PersistenceManager not set in ContextManager!")
            return [system_prompt]

        logger.debug(f"Getting optimal context for thread {thread_id}")
        
        # 1. Get all the thread's messages
        raw_messages = self.persistence_manager.get_all_messages(thread_id)
        
        if not raw_messages or len(raw_messages) == 0:
            logger.debug(f"No existing messages for thread {thread_id}. Using only system prompt.")
            return [system_prompt]
        
        # 2. Build optimal context (system prompt + available messages within token limit)
        # First, count system prompt tokens (always included)
        system_tokens = self._count_tokens([system_prompt], model=model)
        available_token_budget = max_context_tokens - system_tokens - RESERVE_TOKENS
        
        logger.debug(f"Token budget: {available_token_budget} (max: {max_context_tokens}, system: {system_tokens}, reserve: {RESERVE_TOKENS})")
        
        # Transform raw DB messages to format needed for LLM
        filtered_messages = []
        for msg in raw_messages:
            # Skip system messages (we'll add our own)
            if msg.get('role') == 'system':
                continue
                
            # Skip summary messages (they're for context reduction)
            if msg.get('metadata', {}).get('is_summary'):
                continue
                
            # Process the message
            content = msg.get('content')
            role = msg.get('role')
            filtered_messages.append({"role": role, "content": content})
        
        # 3. Truncate message history to fit within token limit
        truncated_messages = self._truncate_messages(filtered_messages, available_token_budget, model=model)
        
        # 4. Combine system prompt with the truncated message history
        optimal_context = [system_prompt] + truncated_messages
        
        return optimal_context

    def _truncate_messages(self, messages: List[Dict[str, Any]], token_budget: int, model: str = "gpt-4") -> List[Dict[str, Any]]:
        """Truncate message history to fit within the token budget.
        
        Args:
            messages: Messages to truncate.
            token_budget: Available tokens for messages.
            model: Model name for token counting.
            
        Returns:
            Truncated list of messages that fits within the token budget.
        """
        if not messages:
            return []
            
        # Try to keep most recent messages, removing older ones first
        if self._count_tokens(messages, model=model) <= token_budget:
            return messages  # Everything fits already
            
        # Start with most recent message and work backwards
        messages_reversed = list(reversed(messages))
        result = []
        token_count = 0
        
        for msg in messages_reversed:
            msg_tokens = self._count_tokens([msg], model=model)
            # Check if adding this message would exceed the budget
            if token_count + msg_tokens > token_budget:
                # If this is the first message we're trying to add, we need to include it
                # even if it exceeds the budget because we need at least one message
                if not result:
                    result.insert(0, msg)
                    logger.warning(f"Single message exceeds token budget: {msg_tokens} > {token_budget}")
                break
                
            # Add message and update count
            result.insert(0, msg)
            token_count += msg_tokens
            
        logger.info(f"Truncated message history: {len(messages)} → {len(result)} messages ({token_count}/{token_budget} tokens)")
        return result 