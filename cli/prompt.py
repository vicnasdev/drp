"""
Shared prompt utilities for interactive argument collection.

Avoid repeating prompt logic across commands. When users don't provide
required arguments, drp will interactively prompt for them if stdin is a TTY.
"""

import sys
from getpass import getpass as _getpass

def is_interactive() -> bool:
    """Check if stdin is a TTY (interactive terminal)."""
    return sys.stdin.isatty()

def prompt_for_value(
    name: str,
    value: str | None = None,
    secret: bool = False,
    allow_empty: bool = False,
) -> str:
    """
    Prompt for a value if missing and in interactive mode.
    
    Args:
        name: User-friendly name for the argument (used in prompt)
        value: Current value (None, empty string, etc)
        secret: If True, use getpass() to hide input (for passwords, tokens)
        allow_empty: If True, allow empty input; if False, keep prompting until non-empty
    
    Returns:
        The original value if provided, or the user's new input
    
    Raises:
        ValueError: If value is missing, stdin is not a TTY, and allow_empty=False
    
    Examples:
        password = prompt_for_value('password', args.password, secret=True)
        key = prompt_for_value('drop key', args.key, allow_empty=False)
        expiry = prompt_for_value('expiry', args.expiry, allow_empty=True)
    """
    
    # Return existing value if provided
    if value:
        return value
    
    # Check if we can prompt
    if not is_interactive():
        if allow_empty:
            return ''
        raise ValueError(
            f"Missing required argument '{name}' and stdin is not interactive. "
            f"Provide the value as an argument or run in an interactive terminal."
        )
    
    # Prompt for input
    while True:
        if secret:
            user_input = _getpass(f"Enter {name}: ")
        else:
            user_input = input(f"Enter {name}: ").strip()
        
        # If empty and not allowed, prompt again
        if not user_input and not allow_empty:
            print(f"→ {name} cannot be empty. Try again.", file=sys.stderr)
            continue
        
        return user_input

def prompt_confirm(
    message: str,
    default: bool = False,
) -> bool:
    """
    Prompt user for yes/no confirmation.
    
    Args:
        message: The prompt message
        default: Default value if user just presses enter
    
    Returns:
        True if user confirms, False otherwise
    
    Raises:
        ValueError: If stdin is not a TTY
    
    Examples:
        if prompt_confirm("Delete this drop?", default=False):
            # delete it
    """
    if not is_interactive():
        return default
    
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        choice = input(f"{message} {hint}: ").strip().lower()
        if not choice:
            return default
        if choice in ('y', 'yes'):
            return True
        if choice in ('n', 'no'):
            return False
        print("→ Please enter 'y' or 'n'.", file=sys.stderr)
