# utils/formatters.py

import re

# Регулярка для поиска тройных бэктиков, инлайн-кода или обычного текста
PATTERN = re.compile(
    r'(?P<codeblock>```(?:text)?\n.*?```)|(?P<inline>`[^`]+`)|(?P<text>[^`]+)',
    flags=re.DOTALL
)

# Спецсимволы MarkdownV2, которые нужно экранировать (кроме бэктиков)
SPECIAL_CHARS = r'_*[]()~>#+-=|{}.!'

def escape_markdown_v2(text: str) -> str:
    """
    Экранирование спецсимволов MarkdownV2 в обычном тексте.
    """
    return re.sub(f'([{SPECIAL_CHARS}])', r'\\\1', text)

def escape_markdown_v2_advanced(text: str) -> str:
    """
    Расширенное экранирование MarkdownV2:
      - Не трогает содержимое в ```...```
      - Не трогает содержимое в `...`
      - Экранирует всё остальное
    """
    if not isinstance(text, str):
        text = str(text)

    result_parts = []
    last_pos = 0

    for match in re.finditer(PATTERN, text):
        codeblock = match.group('codeblock')
        inline = match.group('inline')
        plain_text = match.group('text')

        if codeblock:
            # Добавляем кодовый блок без изменений
            result_parts.append(codeblock)
        elif inline:
            # Добавляем инлайн-код без изменений
            result_parts.append(inline)
        elif plain_text:
            # Экранируем обычный текст
            escaped = escape_markdown_v2(plain_text)
            result_parts.append(escaped)

        last_pos = match.end()

    # Обрабатываем остаток текста после последнего совпадения
    if last_pos < len(text):
        tail_text = text[last_pos:]
        escaped_tail = escape_markdown_v2(tail_text)
        result_parts.append(escaped_tail)

    return ''.join(result_parts)
