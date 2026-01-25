"""
Context management utilities for handling model context length limits.
"""
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Model context length limits (in tokens)
# Approximate: 1 token ≈ 4 characters for English/code
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "qwen2.5-coder:14b": 16384, # Ridotto per stare in VRAM (16GB) con KV cache
    "qwen2.5-coder": 16384,
    "llama3.1:8b": 8192,
    "llama3.1": 8192,
    "llama3.3:70b": 131072,
    "llama3.3": 131072,
    # Default fallback
    "default": 4096,
}

def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.
    Approximation: ~3 characters per token for English/code (more conservative for code).
    """
    if not text:
        return 0
    # Conservative estimate for code: 3 chars per token
    return len(text) // 3

def get_model_context_limit(model_name: str) -> int:
    """
    Get context length limit for a model.
    
    Args:
        model_name: Model name (e.g., "ollama/qwen2.5-coder:14b")
    
    Returns:
        Context limit in tokens
    """
    # Extract model name without provider prefix
    model_key = model_name
    if "/" in model_name:
        model_key = model_name.split("/", 1)[1]
    
    # Try exact match first
    if model_key in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model_key]
    
    # Try partial matches (e.g., "qwen2.5-coder:14b" matches "qwen2.5-coder")
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key in model_key or model_key.startswith(key.split(":")[0]):
            return limit
    
    # Default fallback
    logger.warning(f"Unknown model {model_name}, using default context limit of {MODEL_CONTEXT_LIMITS['default']} tokens")
    return MODEL_CONTEXT_LIMITS["default"]

def truncate_context_intelligently(
    context: str,
    max_tokens: int,
    reserve_tokens: int = 1000,
    model_name: Optional[str] = None
) -> str:
    """
    Truncate context intelligently, preserving most important parts.
    
    Strategy:
    1. Keep the beginning (story details, current task)
    2. Truncate from the middle/end (full_concatenation)
    3. Preserve structure markers
    
    Args:
        context: Full context string
        max_tokens: Maximum tokens allowed
        reserve_tokens: Tokens to reserve for prompt/response (default: 1000)
        model_name: Model name for logging
    
    Returns:
        Truncated context string
    """
    if not context:
        return context
    
    # Calculate available tokens
    available_tokens = max_tokens - reserve_tokens
    if available_tokens < 500:
        logger.warning(f"Very limited context space: {available_tokens} tokens available")
        available_tokens = max(500, available_tokens)
    
    # Estimate current token count
    current_tokens = estimate_tokens(context)
    
    if current_tokens <= available_tokens:
        return context
    
    # Need to truncate
    logger.warning(
        f"Context too long: {current_tokens} tokens (limit: {available_tokens}). "
        f"Truncating... (model: {model_name or 'unknown'})"
    )
    
    # Strategy: Keep beginning (story context) and truncate from the middle
    # New markers for lean context
    story_marker = "=== CURRENT USER STORY TO IMPLEMENT ==="
    progress_marker = "=== PROGRESS TRACKING (tasks.md) ==="
    manifest_marker = "=== AVAILABLE SPECIFICATION FILES ==="
    
    # Old markers (fallback)
    old_story_marker = "=== CURRENT USER STORY ==="
    old_spec_marker = "=== FULL SPECIFICATION CONTEXT ==="
    
    if story_marker in context:
        # We have the new lean structure
        # The story and feature overview are usually at the beginning
        # If we need to truncate, we can truncate from the end of tasks.md content 
        # or the manifest if it gets too large for some reason.
        pass # Fallback to simple truncation if lean context is somehow huge
    elif old_story_marker in context and old_spec_marker in context:
        # Legacy structure truncation logic
        parts = context.split(old_spec_marker, 1)
        story_part = parts[0]
        spec_part = parts[1] if len(parts) > 1 else ""
        
        story_tokens = estimate_tokens(story_part)
        
        if story_tokens > available_tokens * 0.8:
            story_chars = (available_tokens * 0.8 * 3)
            truncated_story = story_part[:int(story_chars)]
            truncated_story += "\n\n[Context truncated due to length limits...]"
            return truncated_story
        
        spec_available = available_tokens - story_tokens - 200
        if spec_available > 0:
            spec_chars = spec_available * 3
            truncated_spec = spec_part[:int(spec_chars)]
            truncated_spec += "\n\n[Specification context truncated due to length limits...]"
            return story_part + old_spec_marker + "\n" + truncated_spec
        else:
            return story_part + "\n\n[Specification context omitted due to length limits]"
    
    # Fallback: simple truncation from end
    max_chars = available_tokens * 3
    truncated = context[:int(max_chars)]
    truncated += "\n\n[Context truncated due to length limits...]"
    return truncated

def limit_context_for_model(
    context: str,
    model_name: str,
    reserve_tokens: int = 1000,
    verbose: bool = False
) -> str:
    """
    Limit context to fit within model's context length limit.
    
    Args:
        context: Full context string
        model_name: Model name (e.g., "ollama/qwen2.5-coder:14b")
        reserve_tokens: Tokens to reserve for prompt/response
        verbose: Whether to log detailed information
    
    Returns:
        Limited context string
    """
    if not context:
        return context
    
    # Get model limit
    max_tokens = get_model_context_limit(model_name)
    
    if verbose:
        current_tokens = estimate_tokens(context)
        logger.debug(f"Context: {current_tokens} tokens, Model limit: {max_tokens} tokens (model: {model_name})")
    
    # Truncate if needed
    limited = truncate_context_intelligently(
        context,
        max_tokens,
        reserve_tokens=reserve_tokens,
        model_name=model_name
    )
    
    if limited != context:
        original_tokens = estimate_tokens(context)
        limited_tokens = estimate_tokens(limited)
        logger.warning(
            f"Context truncated: {original_tokens} → {limited_tokens} tokens "
            f"(saved {original_tokens - limited_tokens} tokens, model: {model_name})"
        )
    
    return limited
