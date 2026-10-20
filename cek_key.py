import os, requests
from dotenv import load_dotenv

load_dotenv(override=True)
k = os.getenv("OPENROUTER_API_KEY", "")
print("ada isi:", bool(k))
print("awalan :", k[:9])            # harus sk-or-v1-
print("panjang:", len(k))           # biasanya sekitar 73
print("ada spasi/kutip nyasar:", k != k.strip().strip('"\''))

r = requests.get("https://openrouter.ai/api/v1/auth/key",
                 headers={"Authorization": f"Bearer {k}"})
print("status :", r.status_code)    # 200 = key valid
print(r.text[:200])