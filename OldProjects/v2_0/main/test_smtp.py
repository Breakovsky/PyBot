# -*- coding: utf-8 -*-
"""
Тест SMTP подключения
"""

import smtplib
import socket
import ssl
import sys
import io
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
TEST_EMAIL = "rodionov.sa@meb52.com"

print("=" * 50)
print("[TEST] SMTP Connection")
print("=" * 50)
print(f"\nHost: {SMTP_HOST}")
print(f"Port: {SMTP_PORT}")
print(f"User: {SMTP_USER}")
print(f"Password: {'*' * min(len(SMTP_PASSWORD), 8)}...")

# Тест 1: SSL (порт 465)
print("\n" + "-" * 50)
print("[TEST 1] SMTP with SSL (port 465)")
try:
    print("  Connecting with SSL...")
    context = ssl.create_default_context()
    server = smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30, context=context)
    print("  Connected!")
    
    print("  Logging in...")
    server.login(SMTP_USER, SMTP_PASSWORD)
    print("  Login OK!")
    
    print(f"  Sending test email to {TEST_EMAIL}...")
    msg = MIMEText("Тестовое письмо от OTRS Bot. Код: 123456")
    msg['Subject'] = 'Тест SMTP - код 123456'
    msg['From'] = SMTP_USER
    msg['To'] = TEST_EMAIL
    server.send_message(msg)
    print("  Email sent!")
    
    server.quit()
    print("\n  [SUCCESS] SMTP SSL works!")
except Exception as e:
    print(f"  [ERROR] {type(e).__name__}: {e}")

# Тест 2: TLS (порт 587)
print("\n" + "-" * 50)
print("[TEST 2] SMTP with STARTTLS (port 587)")
try:
    print("  Connecting...")
    server = smtplib.SMTP(SMTP_HOST, 587, timeout=30)
    print("  Connected!")
    
    print("  Starting TLS...")
    server.starttls()
    print("  TLS OK!")
    
    print("  Logging in...")
    server.login(SMTP_USER, SMTP_PASSWORD)
    print("  Login OK!")
    
    server.quit()
    print("\n  [SUCCESS] SMTP TLS works!")
except Exception as e:
    print(f"  [ERROR] {type(e).__name__}: {e}")

# Тест 3: Без шифрования (порт 25)
print("\n" + "-" * 50)
print("[TEST 3] SMTP plain (port 25)")
try:
    print("  Connecting...")
    server = smtplib.SMTP(SMTP_HOST, 25, timeout=30)
    print("  Connected!")
    
    print("  Logging in...")
    server.login(SMTP_USER, SMTP_PASSWORD)
    print("  Login OK!")
    
    server.quit()
    print("\n  [SUCCESS] SMTP plain works!")
except Exception as e:
    print(f"  [ERROR] {type(e).__name__}: {e}")

print("\n" + "=" * 50)
print("[DONE]")
