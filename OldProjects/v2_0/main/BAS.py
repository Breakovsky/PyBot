# main/my_bot_service.py

import win32service
import win32serviceutil
import win32event
import servicemanager
import logging
import asyncio
import nest_asyncio

from utils.logger import setup_logger
from modules.aiogram_bot import main as aiogram_main

class MyBotService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SoftBot"
    _svc_display_name_ = "SoftBot Service"
    _svc_description_ = "Telegram Bot that runs as a Windows service"

    def __init__(self, args):
        super().__init__(args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.loop = None

    def SvcStop(self):
        """
        Handles service stop requests.
        """
        servicemanager.LogInfoMsg("MyBotService: Received stop signal.")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        """
        Runs the service.
        """
        servicemanager.LogInfoMsg("MyBotService: Starting service...")
        setup_logger("bot_service.log", logging.DEBUG)
        nest_asyncio.apply()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(aiogram_main())
            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        except Exception as e:
            logging.error(f"Service encountered an error: {e}")
        finally:
            self.loop.close()
            servicemanager.LogInfoMsg("MyBotService: Service stopped.")

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(MyBotService)
