# main.py — entrypoint for the bot
import sys
import time
print("Python executable:", sys.executable)
print("Python version:", sys.version)
# import & run your bot
import DiscordGemini  # assumes your code is in DiscordGemini.py and protected by if __name__ == "__main__"
# if your DiscordGemini.py runs on import, instead do:
# from DiscordGemini import run_bot
# run_bot()
time.sleep(2)  # keep logs flush
