import asyncio
import getpass
import qrcode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from PIL import Image

api_id = 
api_hash = ""

SESSION_FILE = "session.session"

async def main():
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        qr_login = await client.qr_login()
        img = qrcode.make(qr_login.url)
        img.show()
        print("📲 Сканируй QR в Telegram → Устройства")

        try:
            await qr_login.wait()
        except SessionPasswordNeededError:
            password = getpass.getpass("🔐 Введи пароль 2FA: ")
            await client.sign_in(password=password)

    with open(SESSION_FILE, "w") as f:
        f.write(client.session.save())

    print("✅ Сессия сохранена. Повторный вход больше не нужен.")
    await client.disconnect()

asyncio.run(main())
