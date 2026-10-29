from llm import client, ask, CHEAP, STRONG

print("Models your key can use:")
for m in client().models.list():
    if "gemini" in m.name:
        print("  ", m.name.replace("models/", ""))
print("CHEAP :", CHEAP, ask('Reply as JSON: {"ok": true}', model=CHEAP))
print("STRONG:", STRONG, ask('Reply as JSON: {"ok": true}', model=STRONG))
