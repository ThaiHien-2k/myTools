import time
import sys

print("Dev Server Manager Service Started.")
print("The API endpoints in dashboard are now active for NPM management.")
print("---")
print("Access the Web UI to manage your NPM projects.")
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    print("Stopping Dev Server Manager...")
    sys.exit(0)
