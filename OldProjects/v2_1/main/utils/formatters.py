"""
Утилиты для форматирования текста.
"""

import re


def escape_html(text: str) -> str:
    """Экранирует HTML символы."""
    if not text:
        return ""
    
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2."""
    if not text:
        return ""
    
    # Символы, которые нужно экранировать в MarkdownV2
    special_chars = r'_*[]()~`>#+-=|{}.!'
    
    result = str(text)
    for char in special_chars:
        result = result.replace(char, f'\\{char}')
    
    return result

