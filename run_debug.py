from telethon_listener import process_file_and_scan
import time

print("Running local test on incoming_targets/hq_1115_HOTMAIL HQ.txt...")
start = time.time()
try:
    process_file_and_scan('test.txt')
    print(f"Finished in {time.time() - start:.2f} seconds.")
except Exception as e:
    print(f"CRASHED! Error: {e}")
