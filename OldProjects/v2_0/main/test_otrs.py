# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки подключения к OTRS.
Запуск: python test_otrs.py
"""

import asyncio
import aiohttp
import sys
import io
import json
from pathlib import Path

# Фикс кодировки для Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import os

# Загружаем .env
load_dotenv(Path(__file__).parent.parent / ".env")

OTRS_URL = os.getenv("OTRS_URL", "").rstrip('/').replace('/index.pl', '')
OTRS_USERNAME = os.getenv("OTRS_USERNAME", "")
OTRS_PASSWORD = os.getenv("OTRS_PASSWORD", "")
OTRS_WEBSERVICE = os.getenv("OTRS_WEBSERVICE", "TelegramBot")


async def test_connection():
    print("=" * 50)
    print("[TEST] OTRS - Check ticket states")
    print("=" * 50)
    
    if not OTRS_URL or not OTRS_USERNAME or not OTRS_PASSWORD:
        print("\n[ERROR] OTRS config not set in .env")
        return
    
    api_base = f"{OTRS_URL}/nph-genericinterface.pl/Webservice/{OTRS_WEBSERVICE}"
    
    async with aiohttp.ClientSession() as session:
        # 1. Поиск всех тикетов (без фильтра)
        print("\n[TEST 1] All tickets (no state filter)...")
        
        search_url = f"{api_base}/TicketSearch"
        params = {
            "UserLogin": OTRS_USERNAME,
            "Password": OTRS_PASSWORD,
            "Limit": 5
        }
        
        try:
            async with session.get(search_url, params=params, timeout=30) as response:
                text = await response.text()
                print(f"   HTTP: {response.status}")
                
                data = json.loads(text) if text else {}
                ticket_ids = data.get("TicketID", [])
                print(f"   Found: {len(ticket_ids)} tickets")
                
                # 2. Получаем детали первых тикетов
                if ticket_ids:
                    print("\n[TEST 2] Ticket details and states...")
                    
                    for tid in ticket_ids[:5]:
                        get_url = f"{api_base}/TicketGet"
                        params = {
                            "UserLogin": OTRS_USERNAME,
                            "Password": OTRS_PASSWORD,
                            "TicketID": tid
                        }
                        
                        async with session.get(get_url, params=params, timeout=30) as resp:
                            tdata = await resp.json()
                            ticket = tdata.get("Ticket", [{}])[0] if tdata.get("Ticket") else {}
                            
                            print(f"\n   Ticket #{ticket.get('TicketNumber', tid)}:")
                            print(f"     Title: {ticket.get('Title', 'N/A')}")
                            print(f"     State: '{ticket.get('State', 'N/A')}'")
                            print(f"     StateType: '{ticket.get('StateType', 'N/A')}'")
                            print(f"     Queue: {ticket.get('Queue', 'N/A')}")
                
        except Exception as e:
            print(f"   [ERROR] {e}")
    
    print("\n" + "=" * 50)
    print("[DONE]")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_connection())
